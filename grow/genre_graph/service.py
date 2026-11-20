import json
from uuid import UUID, uuid4

from django.db import connection, transaction
from django.utils.dateparse import parse_datetime
from the_music_tree_genre_graph import GenreGraph, GraphValidationError
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks
from the_music_tree_genre_kit.genre_graph.assignments import assignment_snapshot, register_evidence
from the_music_tree_genre_kit.genre_graph.models import (
    GenreGraphAssignmentState,
    GenreGraphAttributionRevision,
    GenreGraphDataset,
    GenreGraphNode,
    GenreGraphRevision,
)
from the_music_tree_genre_kit.genre_graph.publication import publish_staged_attributions
from the_music_tree_genre_kit.genre_graph.storage import (
    GraphRevisionConflict,
    graph_write_transaction,
    merge_graph_nodes,
    replace_graph,
    replace_track_attributions,
)

from grow.genre_graph.models import GenreGraphAssignmentBackup, GenreGraphImport
from grow.genre_music.source_gate import lock_catalogue_sources
from grow.genre_tree.bulk_import.merge import load_curation_export, parse_curation_exported_on
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Criteria import Criteria
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationExport import CurationExport
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.song.Song import Song

DATASET_KEY = "grow"


def validate_song_attributions(attributions: object) -> None:
    if not isinstance(attributions, dict):
        raise GraphValidationError("Song attributions must be an object")
    if len(attributions) > 1:
        raise GraphValidationError("A song can have at most one directly assigned genre")


def _normalized_graph(payload: dict) -> GenreGraph:
    graph = GenreGraph(payload)
    normalized = graph.to_payload()
    # These arrays are sets of decisions; producer iteration order is not a new revision.
    for field in ("nodes", "relations", "canonicalRoots"):
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


def _validate_provenance(provenance) -> None:
    if (
        not isinstance(provenance, dict)
        or set(provenance) != {"decisionId", "source", "rationale"}
        or any(not isinstance(value, str) or not value.strip() for value in provenance.values())
    ):
        raise GraphValidationError("Explicit decisionId, source and rationale provenance is required")


def _validate_retirements(decisions, retired: set, retained: set) -> None:
    if not isinstance(decisions, dict) or set(decisions) != retired:
        raise GraphValidationError("Retirements must name every removed identity exactly once")
    for identity, decision in decisions.items():
        if not isinstance(decision, dict) or set(decision) != {"target", "provenance"}:
            raise GraphValidationError(
                f"Retirement requires an explicit target (identity or null) and provenance: {identity}"
            )
        if decision["target"] is not None and (
            not isinstance(decision["target"], str) or decision["target"] not in retained
        ):
            raise GraphValidationError(f"Retirement target must be a retained semantic identity: {identity}")
        _validate_provenance(decision["provenance"])


def _project_display_tree(graph, bindings: dict) -> dict:
    """Map each bound genre pk to its (parent pk, root pk) from the graph's display parents."""
    projected = {}
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
        projected[pk] = (bindings[parent] if parent else None, bindings[root] if root else pk)
    return projected


def _publish_revision(
    *, dataset, graph, bindings: dict, genres: dict, retirements: dict, exported_on, initial: bool, state
) -> None:
    """Record the receipt of a graph revision just written and project it onto the genre rows.

    Shared by the explicit import and by a node merge: both own their locks and their validation."""
    receipt = GenreGraphImport.objects.create(
        revision=dataset.revision,
        mapping={identity: str(pk) for identity, pk in bindings.items()},
        retirements=retirements,
        curation_exported_on=exported_on,
        has_initial_assignment_backup=initial,
    )
    if initial:
        _backup_assignments(receipt)
    nodes = {node.identity: node for node in dataset.nodes.all()}
    # Bind first so distinct concepts can use the same display label.
    projection = []
    bound = []
    for identity, pk in bindings.items():
        if pk in genres:
            genre = genres[pk]
            genre.graph_node = nodes[identity]
            genre.semantic_identity = identity
            bound.append(genre)
    Genre.objects.bulk_update(bound, ["graph_node", "semantic_identity"], batch_size=250)
    metadata = []
    playlist_criteria = set(
        CriteriaPlaylist.objects.filter(criteria_id__in=bindings.values()).values_list("criteria_id", flat=True)
    )
    for identity, pk in bindings.items():
        data = graph.node(identity)
        genre = genres.get(pk)
        tree_name = "canonical" if graph.canonical_state(identity) == "canonical" else "regional"
        if genre is None:
            genre = Genre(
                uuid=pk,
                criteria_ptr_id=pk,
                graph_node=nodes[identity],
                semantic_identity=identity,
                user=None,
                _name=data["name"],
                tree_name=tree_name,
                is_umbrella=data.get("isUmbrella", False),
            )
            genre.root = genre
            genre.save()
        else:
            # The complete semantic graph was validated above; legacy per-node saves
            # would validate a temporary display projection while bindings are rebuilt.
            genre._name = data["name"]
            genre.tree_name = tree_name
            genre.is_umbrella = data.get("isUmbrella", False)
            metadata.append(genre)
        genres[pk] = genre
        if pk not in playlist_criteria:
            CriteriaPlaylist.objects.create(criteria=genre, user=None, type_id=int(CriteriaTypePks.GENRE))
    Genre.objects.bulk_update(metadata, ["_name", "tree_name", "is_umbrella"], batch_size=250)
    for pk, (parent_id, root_id) in _project_display_tree(graph, bindings).items():
        genre = genres[pk]
        genre.parent_id = parent_id
        genre.root_id = root_id
        projection.append(genre)
    Genre.objects.bulk_update(projection, ["parent", "root"], batch_size=250)
    if initial:
        _migrate_assignments(dataset)
    state.applied_export_on = exported_on
    state.save(update_fields=["applied_export_on"])
    GenreTreeVersion.objects.filter(pk=1).update(token=uuid4())


def _validate_no_merged_source(graph) -> None:
    """`replace_graph` reactivates any inactive node the payload names, which would silently undo a merge."""
    keys = CurationEntry.objects.filter(user=None, list_name="genre_merges").values_list("key", flat=True)
    revived = sorted(tuple(key.split("\t")) for key in keys if key.split("\t")[0] in graph.node_ids)
    if revived:
        pairs = ", ".join(f"{source} -> {target}" for source, target in revived)
        raise GraphValidationError(
            f"The graph contains merged source nodes: {pairs}. Delete the genre_merges rule to undo a merge "
            "(attributions do not move back), or have the upstream graph emit the merge."
        )


def _check_canonical_roots(graph: GenreGraph, export: CurationExport) -> None:
    """The graph's `canonicalRoots` are what the export's `canonical_roots` list said, whatever was edited since."""
    try:
        expected = export.canonical_roots
    except ValueError as error:
        raise GraphValidationError(str(error)) from error
    declared = {root["nodeId"] for root in graph.to_payload()["canonicalRoots"]}
    if declared != expected:
        raise GraphValidationError(
            "canonicalRoots differ from the export's canonical_roots list: "
            f"only in the graph {sorted(declared - expected)}, only in the export {sorted(expected - declared)}"
        )


@transaction.atomic
def import_reference_graph(
    *,
    payload: dict,
    mapping: dict,
    expected_revision: UUID | None,
    curation_exported_on,
    retirements: dict | None = None,
):
    """Cut over explicitly; labels never resolve identities and no song is discarded."""
    graph = _normalized_graph(payload)
    lock_catalogue_sources()
    current = GenreGraphDataset.objects.select_for_update().filter(pk=DATASET_KEY).first()
    if (current is None) != (expected_revision is None) or (
        current is not None and current.revision != expected_revision
    ):
        raise GraphRevisionConflict("Reference graph revision changed; reload before importing")
    _validate_no_merged_source(graph)
    state = _curation_state()
    export = load_curation_export(curation_exported_on)
    exported_on = export.exported_on
    if parse_curation_exported_on(payload.get("curationExportedOn")) != exported_on:
        raise GraphValidationError("Curation provenance must match the graph's curationExportedOn")
    _check_canonical_roots(graph, export)
    existing = dict(
        Genre.objects.filter(user__isnull=True, semantic_identity__isnull=False).values_list("semantic_identity", "pk")
    )
    bindings = _bindings(graph, mapping, existing)
    active = dict(
        Genre.objects.filter(graph_node__dataset_id=DATASET_KEY, graph_node__is_active=True).values_list(
            "semantic_identity", "pk"
        )
    )
    retired = set(active) - graph.node_ids
    retirements = {} if retirements is None else retirements
    _validate_retirements(retirements, retired, graph.node_ids)
    genres = dict(Genre.objects.filter(user__isnull=True).in_bulk())
    unmapped = {pk for pk, genre in genres.items() if genre.semantic_identity is None} - set(bindings.values())
    if unmapped:
        raise GraphValidationError(f"Unmapped existing genre UUIDs: {sorted(map(str, unmapped))}")
    for identity, value in mapping.items():
        if value is not None and bindings[identity] not in genres:
            raise GraphValidationError(f"Mapping must reference an existing ownerless genre: {identity}")
        if bindings[identity] in genres and genres[bindings[identity]].semantic_identity not in (None, identity):
            raise GraphValidationError(f"Genre UUID already belongs to another semantic identity: {identity}")
    if current is not None and current.payload == graph.to_payload():
        if bindings != active:
            raise GraphValidationError("An unchanged graph cannot change its bindings")
        return current
    dataset = replace_graph(
        key=DATASET_KEY, payload=graph.to_payload(), expected_revision=expected_revision, retirements=retirements
    )
    _publish_revision(
        dataset=dataset,
        graph=graph,
        bindings=bindings,
        genres=genres,
        retirements=retirements,
        exported_on=exported_on,
        initial=current is None,
        state=state,
    )
    dataset.refresh_from_db()
    return dataset


@transaction.atomic
def merge_reference_genres(*, source: Genre, target: Genre, provenance: dict) -> GenreGraphDataset:
    """Absorb a concept into another as one graph revision: the kit moves relations and attributions through the
    retirement and the source's node turns inactive, so no genre binding is ever deleted."""
    if source.semantic_identity is None or target.semantic_identity is None:
        raise GraphValidationError("Both genres must be bound to a reference graph node to be merged")
    _validate_provenance(provenance)
    lock_catalogue_sources()
    current = GenreGraphDataset.objects.select_for_update().filter(pk=DATASET_KEY).first()
    if current is None:
        raise GraphValidationError("Import the reference graph with an explicit identity mapping first")
    state = _curation_state()
    dataset = merge_graph_nodes(
        key=DATASET_KEY,
        source=source.semantic_identity,
        target=target.semantic_identity,
        provenance=provenance,
        expected_revision=current.revision,
    )
    if dataset.revision == current.revision:
        return dataset
    graph = _normalized_graph(dataset.payload)
    genres = dict(Genre.objects.filter(user__isnull=True).in_bulk())
    bindings = {
        identity: pk
        for identity, pk in Genre.objects.filter(
            graph_node__dataset_id=DATASET_KEY, graph_node__is_active=True, user__isnull=True
        ).values_list("semantic_identity", "pk")
        if identity in graph.node_ids
    }
    retirements = {source.semantic_identity: {"target": target.semantic_identity, "provenance": provenance}}
    # A merge is not a new export: the curation provenance stays the one of the last import, or of the graph itself
    # when it was installed without one.
    exported_on = state.applied_export_on or parse_datetime(dataset.payload["curationExportedOn"])
    _publish_revision(
        dataset=dataset,
        graph=graph,
        bindings=bindings,
        genres=genres,
        retirements=retirements,
        exported_on=exported_on,
        initial=False,
        state=state,
    )
    receipt = GenreGraphImport.objects.get(pk=dataset.revision)
    receipt.mapping = {**receipt.mapping, source.semantic_identity: str(source.pk)}
    receipt.save(update_fields=["mapping"])
    dataset.refresh_from_db()
    return dataset


@transaction.atomic
def restore_reference_graph(
    *, revision: UUID, expected_revision: UUID, retirements: dict | None = None
) -> GenreGraphDataset:
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
        retirements=retirements,
    )


@transaction.atomic
def write_song_attributions(
    *,
    song_id: UUID,
    attributions: dict,
    expected_revision: UUID,
    expected_membership_revision: UUID,
    expected_assignment_revision: UUID | None,
) -> GenreGraphDataset:
    validate_song_attributions(attributions)
    lock_catalogue_sources()
    with graph_write_transaction(key=DATASET_KEY, expected_revision=expected_revision) as dataset:
        if dataset.membership_revision != expected_membership_revision:
            raise GraphRevisionConflict("Reference memberships changed; reload before assigning songs")
        Song.objects.select_for_update().get(pk=song_id, user__isnull=True)
        replace_track_attributions(
            key=DATASET_KEY,
            track_id=song_id,
            attributions=attributions,
            expected_revision=expected_revision,
            expected_assignment_revision=expected_assignment_revision,
        )
        dataset.refresh_from_db()
        return dataset


@transaction.atomic
def set_song_genre(song: Song, genre: Genre | None, *, provenance: dict) -> bool:
    """Single writer entry for a song's direct genre. With a reference dataset installed the attribution is the only
    authority (`Track.genre_id` is left alone) and True is returned; without one, False tells the caller to use the
    legacy column. Gate and dataset locks are taken here, before the song row, in the canonical order."""
    lock_catalogue_sources()
    dataset = GenreGraphDataset.objects.select_for_update().filter(pk=DATASET_KEY).first()
    if dataset is None:
        return False
    attributions = {}
    if genre is not None:
        node = genre.graph_node
        if node is None or not node.is_active:
            raise GraphValidationError(f"{genre.name} has no active node in the reference graph")
        attributions[node.identity] = [provenance]
    state = GenreGraphAssignmentState.objects.filter(dataset=dataset, track_id=song.pk).first()
    write_song_attributions(
        song_id=song.pk,
        attributions=attributions,
        expected_revision=dataset.revision,
        expected_membership_revision=dataset.membership_revision,
        expected_assignment_revision=state.revision if state else None,
    )
    return True


def song_genre(song: Song) -> Genre | None:
    """The song's effective genre, materialised on `grow_song.genre_id` (legacy column before the dataset)."""
    return Song.objects.select_related("membership_genre").get(pk=song.pk).membership_genre


def song_attribution_state(song: Song) -> tuple[dict, UUID | None] | None:
    """The song's current attributions and assignment revision, or None before the reference dataset exists."""
    dataset = GenreGraphDataset.objects.filter(pk=DATASET_KEY).first()
    if dataset is None:
        return None
    state = GenreGraphAssignmentState.objects.filter(dataset=dataset, track_id=song.pk).first()
    return assignment_snapshot(dataset=dataset, track_id=song.pk), state.revision if state else None


@transaction.atomic
def restore_song_snapshot(song: Song, attributions: dict, *, expected_assignment_revision: UUID | None) -> None:
    """Puts back attributions captured by `song_attribution_state`; GraphRevisionConflict when the song's assignment
    revision moved since `expected_assignment_revision`."""
    lock_catalogue_sources()
    dataset = GenreGraphDataset.objects.select_for_update().get(pk=DATASET_KEY)
    write_song_attributions(
        song_id=song.pk,
        attributions=attributions,
        expected_revision=dataset.revision,
        expected_membership_revision=dataset.membership_revision,
        expected_assignment_revision=expected_assignment_revision,
    )


@transaction.atomic
def restore_song_attributions(
    *,
    song_id: UUID,
    revision: UUID,
    expected_revision: UUID,
    expected_membership_revision: UUID,
    expected_assignment_revision: UUID | None,
) -> GenreGraphDataset:
    lock_catalogue_sources()
    with graph_write_transaction(key=DATASET_KEY, expected_revision=expected_revision) as dataset:
        if dataset.membership_revision != expected_membership_revision:
            raise GraphRevisionConflict("Reference memberships changed; reload before restoring songs")
        Song.objects.select_for_update().get(pk=song_id, user__isnull=True)
        archived = GenreGraphAttributionRevision.objects.get(dataset=dataset, track_id=song_id, revision=revision)
        validate_song_attributions(archived.attributions)
        replace_track_attributions(
            key=DATASET_KEY,
            track_id=song_id,
            attributions=archived.attributions,
            expected_revision=expected_revision,
            expected_assignment_revision=expected_assignment_revision,
        )
        dataset.refresh_from_db()
        return dataset


@transaction.atomic
def restore_initial_assignments(
    *, revision: UUID, expected_revision: UUID, expected_membership_revision: UUID, provenance: dict
) -> GenreGraphDataset:
    """Restore the initial assignment snapshot through permanent semantic bindings."""
    _validate_provenance(provenance)
    lock_catalogue_sources()
    with graph_write_transaction(key=DATASET_KEY, expected_revision=expected_revision) as dataset:
        if dataset.membership_revision != expected_membership_revision:
            raise GraphRevisionConflict("Reference memberships changed; reload before restoring initial assignments")
        if not GenreGraphImport.objects.filter(pk=revision, has_initial_assignment_backup=True).exists():
            raise GraphValidationError("No initial assignment backup exists for this revision")
        imported_id = GenreGraphImport._meta.pk.get_db_prep_value(revision, connection)
        quote = connection.ops.quote_name
        backup, song = (quote(model._meta.db_table) for model in (GenreGraphAssignmentBackup, Song))
        population = (
            f"SELECT b.song_uuid AS track_id, b.genre_uuid AS genre_id FROM {backup} b "
            f"JOIN {song} s ON s.track_id = b.song_uuid WHERE b.imported_id = %s"
        )
        _publish_legacy_assignments(dataset, population, [imported_id], provenance)
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


def _migrate_assignments(dataset) -> None:
    from the_music_tree_genre_kit.track.Track import Track

    quote = connection.ops.quote_name
    track, song = (quote(model._meta.db_table) for model in (Track, Song))
    population = (
        f"SELECT t.uuid AS track_id, t.genre_id FROM {track} t "
        f"JOIN {song} s ON s.track_id = t.uuid WHERE t.user_id IS NULL"
    )
    _publish_legacy_assignments(
        dataset,
        population,
        [],
        {
            "decisionId": "grow-explicit-cutover",
            "source": "existing-genre-uuid",
            "rationale": "Preserve the explicitly mapped existing song assignment",
        },
    )


def _publish_legacy_assignments(dataset, population_sql, params, provenance):
    """Translate the reviewed UUID snapshot into the kit's staged complete sets."""
    from the_music_tree_genre_kit.track.Track import Track

    quote = connection.ops.quote_name
    population = f"grow_assignment_population_{uuid4().hex}"
    desired = f"grow_assignment_desired_{uuid4().hex}"
    p, d = quote(population), quote(desired)
    criteria, node, track = (quote(model._meta.db_table) for model in (Criteria, GenreGraphNode, Track))
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE TEMPORARY TABLE {p} AS {population_sql}", params)
        cursor.execute(
            f"""SELECT EXISTS (SELECT 1 FROM {p} p
            LEFT JOIN {criteria} c ON c.uuid = p.genre_id LEFT JOIN {node} n ON n.id = c.graph_node_id
            JOIN {track} t ON t.uuid = p.track_id WHERE t.user_id IS NOT NULL OR
            (p.genre_id IS NOT NULL AND (n.id IS NULL OR NOT n.is_active OR n.dataset_id <> %s)))""",
            [dataset.pk],
        )
        if cursor.fetchone()[0]:
            raise GraphValidationError("Initial assignment identities must be reactivated before restoring")
        evidence = register_evidence(dataset, [provenance])[provenance["decisionId"]]
        cursor.execute(
            f"""CREATE TEMPORARY TABLE {d} AS
            SELECT p.track_id, c.graph_node_id AS node_id, %s AS evidence_id FROM {p} p
            JOIN {criteria} c ON c.uuid = p.genre_id""",
            [evidence.pk],
        )
        cursor.execute(f"ANALYZE {p}")
        cursor.execute(f"ANALYZE {d}")
        publish_staged_attributions(dataset=dataset, population=population, assignments=desired)
        cursor.execute(f"DROP TABLE {d}")
        cursor.execute(f"DROP TABLE {p}")
