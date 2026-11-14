import json
from uuid import UUID, uuid4

from django.db import connection, transaction
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks
from the_music_tree_genre_kit.genre_graph.graph import GenreGraph, GraphValidationError
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphDataset, GenreGraphRevision
from the_music_tree_genre_kit.genre_graph.storage import (
    GraphRevisionConflict,
    graph_write_transaction,
    replace_graph,
    replace_track_attributions,
    restore_track_attributions,
)

from grow.genre_graph.models import GenreGraphAssignmentBackup, GenreGraphImport
from grow.genre_music.source_gate import lock_catalogue_sources
from grow.genre_tree.bulk_import.merge import parse_curation_exported_on
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Criteria import Criteria
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.song.Song import Song

DATASET_KEY = "grow"


def _normalized_graph(payload: dict) -> GenreGraph:
    graph = GenreGraph(payload)
    normalized = graph.to_payload()
    # These arrays are sets of decisions; producer iteration order is not a new revision.
    for field in ("nodes", "relations", "boundaries"):
        normalized[field].sort(key=lambda row: json.dumps(row, sort_keys=True))
    return GenreGraph(normalized)


def _curation_state() -> CurationSyncState:
    try:
        state = CurationSyncState.objects.select_for_update().get(pk=1)
        GenreTreeVersion.objects.select_for_update().get(pk=1)
    except (CurationSyncState.DoesNotExist, GenreTreeVersion.DoesNotExist) as error:
        raise GraphValidationError(
            "Reference graph import requires the curation and tree-version singletons"
        ) from error
    return state


def reference_dataset() -> GenreGraphDataset:
    try:
        return GenreGraphDataset.objects.get(pk=DATASET_KEY)
    except GenreGraphDataset.DoesNotExist as error:
        raise GraphValidationError("Import the reference graph with an explicit identity mapping first") from error


def _bindings(graph: GenreGraph, mapping: dict, existing: dict) -> dict:
    if not isinstance(mapping, dict) or set(mapping) != graph.node_ids:
        raise GraphValidationError("Mapping must name every semantic identity exactly once")
    result = {}
    for identity, value in mapping.items():
        if value is None:
            result[identity] = existing.get(identity, uuid4())
        else:
            try:
                result[identity] = UUID(str(value))
            except (ValueError, TypeError, AttributeError) as error:
                raise GraphValidationError(f"Invalid genre UUID for {identity}") from error
        if identity in existing and result[identity] != existing[identity]:
            raise GraphValidationError(f"Cannot rebind an existing semantic identity: {identity}")
    if len(set(result.values())) != len(result):
        raise GraphValidationError("Different semantic identities cannot share a genre UUID")
    return result


@transaction.atomic
def import_reference_graph(*, payload: dict, mapping: dict, expected_revision: UUID | None, curation_exported_on):
    """Cut over explicitly; labels never resolve identities and no song is discarded."""
    graph = _normalized_graph(payload)
    lock_catalogue_sources()
    current = GenreGraphDataset.objects.select_for_update().filter(pk=DATASET_KEY).first()
    if (current is None) != (expected_revision is None) or (
        current is not None and current.revision != expected_revision
    ):
        raise GraphRevisionConflict("Reference graph revision changed; reload before importing")
    state = _curation_state()
    exported_on = parse_curation_exported_on(curation_exported_on, state)
    if parse_curation_exported_on(payload.get("curationExportedOn"), state) != exported_on:
        raise GraphValidationError("Curation provenance must match the graph's curationExportedOn")
    existing = dict(Genre.objects.filter(graph_node__dataset_id=DATASET_KEY).values_list("graph_node__identity", "pk"))
    bindings = _bindings(graph, mapping, existing)
    if set(existing) - graph.node_ids:
        raise GraphValidationError("Removing a bound identity requires an explicit migration before replacement")
    genres = dict(Genre.objects.filter(user__isnull=True).in_bulk())
    unmapped = set(genres) - set(bindings.values())
    if unmapped:
        raise GraphValidationError(f"Unmapped existing genre UUIDs: {sorted(map(str, unmapped))}")
    for identity, value in mapping.items():
        if value is not None and bindings[identity] not in genres:
            raise GraphValidationError(f"Mapping must reference an existing ownerless genre: {identity}")
    if current is not None and current.payload == graph.to_payload():
        if bindings != existing:
            raise GraphValidationError("An unchanged graph cannot change its bindings")
        return current
    dataset = replace_graph(key=DATASET_KEY, payload=graph.to_payload(), expected_revision=expected_revision)
    receipt = GenreGraphImport.objects.create(
        revision=dataset.revision,
        mapping={identity: str(pk) for identity, pk in bindings.items()},
        curation_exported_on=exported_on,
    )
    if current is None:
        _backup_assignments(receipt)
    nodes = {node.identity: node for node in dataset.nodes.all()}
    # Bind first so distinct concepts can use the same display label.
    for identity, pk in bindings.items():
        if pk in genres:
            Genre.objects.filter(pk=pk).update(graph_node=nodes[identity])
    for identity, pk in bindings.items():
        data = graph.node(identity)
        genre = genres.get(pk)
        if genre is None:
            genre = Genre(uuid=pk, criteria_ptr_id=pk, graph_node=nodes[identity], user=None, _name=data["name"])
        genre.graph_node = nodes[identity]
        genre._name = data["name"]
        genre.tree_name = "canonical" if data.get("canonicalState") == "canonical" else "regional"
        genre.is_umbrella = data.get("isUmbrella", False)
        genre.parent_id = None
        genre.root = genre
        genre.save()
        genres[pk] = genre
        CriteriaPlaylist.objects.get_or_create(
            criteria=genre, defaults={"user": None, "type_id": int(CriteriaTypePks.GENRE)}
        )
    for identity, pk in bindings.items():
        parent = graph.node(identity).get("displayParentId")
        root = parent
        visited = {identity}
        while root is not None:
            if root in visited:
                raise GraphValidationError("Display-parent projection contains a cycle")
            visited.add(root)
            next_parent = graph.node(root).get("displayParentId")
            if next_parent is None:
                break
            root = next_parent
        Genre.objects.filter(pk=pk).update(
            parent_id=bindings[parent] if parent else None,
            root_id=bindings[root] if root else pk,
        )
    if current is None:
        _migrate_assignments()
    state.applied_export_on = exported_on
    state.save(update_fields=["applied_export_on"])
    GenreTreeVersion.objects.filter(pk=1).update(token=uuid4())
    return dataset


@transaction.atomic
def restore_reference_graph(*, revision: UUID, expected_revision: UUID) -> GenreGraphDataset:
    """Restore the archived graph and UUID bindings through the same validated write path.

    Removing a subsequently bound concept requires an explicit identity migration,
    just as a forward import does; a rollback must never silently discard songs.
    """
    lock_catalogue_sources()
    try:
        archived = GenreGraphRevision.objects.get(dataset_id=DATASET_KEY, revision=revision)
        receipt = GenreGraphImport.objects.get(pk=revision)
    except (GenreGraphRevision.DoesNotExist, GenreGraphImport.DoesNotExist) as error:
        raise GraphValidationError("No complete reference graph archive exists for this revision") from error
    return import_reference_graph(
        payload=archived.payload,
        mapping=receipt.mapping,
        expected_revision=expected_revision,
        curation_exported_on=receipt.curation_exported_on,
    )


@transaction.atomic
def write_song_attributions(
    *, song_id: UUID, attributions: dict, expected_revision: UUID, expected_membership_revision: UUID
) -> GenreGraphDataset:
    lock_catalogue_sources()
    with graph_write_transaction(key=DATASET_KEY, expected_revision=expected_revision) as dataset:
        if dataset.membership_revision != expected_membership_revision:
            raise GraphRevisionConflict("Reference memberships changed; reload before assigning songs")
        Song.objects.select_for_update().get(pk=song_id, user__isnull=True)
        replace_track_attributions(
            key=DATASET_KEY, track_id=song_id, attributions=attributions, expected_revision=expected_revision
        )
        dataset.refresh_from_db()
        return dataset


@transaction.atomic
def restore_song_attributions(
    *, song_id: UUID, revision: UUID, expected_revision: UUID, expected_membership_revision: UUID
) -> GenreGraphDataset:
    lock_catalogue_sources()
    with graph_write_transaction(key=DATASET_KEY, expected_revision=expected_revision) as dataset:
        if dataset.membership_revision != expected_membership_revision:
            raise GraphRevisionConflict("Reference memberships changed; reload before restoring songs")
        Song.objects.select_for_update().get(pk=song_id, user__isnull=True)
        restore_track_attributions(
            key=DATASET_KEY, track_id=song_id, revision=revision, expected_revision=expected_revision
        )
        dataset.refresh_from_db()
        return dataset


def _backup_assignments(receipt: GenreGraphImport) -> None:
    from the_music_tree_genre_kit.track.Track import Track

    quote = connection.ops.quote_name
    backup = quote(GenreGraphAssignmentBackup._meta.db_table)
    song = quote(Song._meta.db_table)
    track = quote(Track._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {backup} (imported_id, song_uuid, genre_uuid) "
            f"SELECT %s, t.uuid, t.genre_id FROM {track} t JOIN {song} s ON s.track_id = t.uuid "
            "WHERE t.user_id IS NULL",
            [GenreGraphImport._meta.pk.get_db_prep_value(receipt.pk, connection)],
        )


def _migrate_assignments() -> None:
    from the_music_tree_genre_kit.track.Track import Track

    quote = connection.ops.quote_name
    attribution = quote(GenreGraphAttribution._meta.db_table)
    track, song, criteria = (quote(model._meta.db_table) for model in (Track, Song, Criteria))
    provenance = GenreGraphAttribution._meta.get_field("provenance").get_db_prep_save(
        {
            "decisionId": "grow-explicit-cutover",
            "source": "existing-genre-uuid",
            "rationale": "Preserve the explicitly mapped existing song assignment",
        },
        connection,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {attribution} (track_id, node_id, provenance) "
            f"SELECT t.uuid, c.graph_node_id, %s FROM {track} t "
            f"JOIN {song} s ON s.track_id = t.uuid JOIN {criteria} c ON c.uuid = t.genre_id "
            "WHERE t.user_id IS NULL AND c.graph_node_id IS NOT NULL",
            [provenance],
        )
