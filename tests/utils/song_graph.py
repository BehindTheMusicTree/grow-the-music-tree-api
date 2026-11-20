from collections import defaultdict

from the_music_tree_genre_kit.genre_graph.models import GenreGraphAssignmentState, GenreGraphDataset
from the_music_tree_genre_kit.genre_graph.storage import replace_graph, replace_track_attributions

from grow.genre_graph.service import DATASET_KEY
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.song.Song import Song


def install_song_graph(assignments, *, classifications=(), node_overrides=None, relations=(), boundaries=()):
    """Install explicit test semantics independently of Song.genre and display parents.

    assignments maps each graph genre to its directly attributed songs, including
    an empty list for nodes with no direct songs. Repeated songs model polygenre.
    """
    node_overrides = node_overrides or {}

    def identity(genre):
        return f"LOCAL:{genre.pk}"

    def provenance(decision):
        return {"decisionId": decision, "source": "fixture:song-graph", "rationale": "Synthetic test decision."}

    nodes = []
    for genre in assignments:
        node = {
            "id": identity(genre),
            "name": genre.name,
            "kind": "genre",
            "canonicalState": "canonical",
            **node_overrides.get(genre, {}),
        }
        if node["kind"] != "genre":
            node.pop("canonicalState", None)
        if node["kind"] == "overview":
            node.update(
                overviewType="current",
                overviewProvenance=provenance(f"overview-{genre.pk}"),
                isUmbrella=True,
            )
        nodes.append(node)
    children = {child for child, _ in classifications}
    entries = [
        (genre, "entry")
        for genre, node in zip(assignments, nodes, strict=True)
        if genre not in children and node.get("canonicalState") == "canonical"
    ]
    payload = {
        "contractVersion": 2,
        "curationExportedOn": "2026-11-14T00:00:00Z",
        "nodes": nodes,
        "relations": [
            {
                "childId": identity(child),
                "parentId": identity(parent),
                "type": relation_type,
                "provenance": provenance(f"{relation_type}-{identity(child)}-{identity(parent)}"),
            }
            for child, parent, relation_type in [
                *((child, parent, "classification") for child, parent in classifications),
                *relations,
            ]
        ],
        "boundaries": [
            {"nodeId": identity(genre), "type": boundary_type, "provenance": provenance(f"{boundary_type}-{genre.pk}")}
            for genre, boundary_type in [*entries, *boundaries]
        ],
    }
    current = GenreGraphDataset.objects.filter(pk=DATASET_KEY).first()
    dataset = replace_graph(key=DATASET_KEY, payload=payload, expected_revision=current.revision if current else None)
    songs = defaultdict(dict)
    for genre, attributed in assignments.items():
        node = dataset.nodes.get(identity=identity(genre))
        Genre.objects.filter(pk=genre.pk).update(graph_node=node, semantic_identity=node.identity)
        for song in attributed:
            songs[song.pk][node.identity] = [provenance(f"song-{song.pk}-{node.identity}")]
    for song_id, attributions in songs.items():
        replace_track_attributions(
            key=DATASET_KEY,
            track_id=song_id,
            attributions=attributions,
            expected_revision=dataset.revision,
            expected_assignment_revision=GenreGraphAssignmentState.objects.filter(dataset=dataset, track_id=song_id)
            .values_list("revision", flat=True)
            .first(),
        )
    return dataset


def install_graph_from_rows():
    """Install the graph the canonical Genre rows describe: parent links as classifications, Song.genre as attributions."""
    genres = list(Genre.objects.filter(user__isnull=True).order_by("created_on"))
    by_pk = {genre.pk: genre for genre in genres}
    songs = defaultdict(list)
    for song in Song.objects.filter(genre__in=genres):
        songs[song.genre_id].append(song)
    # A regional genre with extra primary parents is an expression of each of them; its regional
    # descendants are expressions of the same parents (an expression cannot have classified children).
    expressions = {}
    for genre in genres:
        if genre.tree_name == "canonical":
            continue
        node = genre
        while node is not None:
            targets = [by_pk[pk] for pk in node.additional_primary_parents.values_list("pk", flat=True) if pk in by_pk]
            if targets:
                expressions[genre] = targets
                break
            node = by_pk.get(node.parent_id)
    overrides = {genre: {"canonicalState": "before_entry"} for genre in genres if genre.tree_name != "canonical"}
    for genre in expressions:
        overrides[genre] = {"kind": "expression"}
    return install_song_graph(
        {genre: songs[genre.pk] for genre in genres},
        classifications=[
            (genre, by_pk[genre.parent_id]) for genre in genres if genre.parent_id in by_pk and genre not in expressions
        ],
        relations=[(genre, parent, "expression_style") for genre, parents in expressions.items() for parent in parents],
        node_overrides=overrides,
    )
