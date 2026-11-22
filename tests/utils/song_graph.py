from collections import defaultdict

from the_music_tree_genre_kit.genre_graph.models import GenreGraphAssignmentState, GenreGraphDataset
from the_music_tree_genre_kit.genre_graph.storage import replace_graph, replace_track_attributions

from grow.genre_graph.service import DATASET_KEY
from grow.model.criteria.children.genre.Genre import Genre


def install_song_graph(assignments, *, classifications=(), node_overrides=None, relations=(), regional=None):
    """Install explicit test semantics independently of Song.genre and display parents.

    assignments maps each graph genre to its directly attributed songs, including
    an empty list for nodes with no direct songs. Repeated songs model polygenre.
    Every genre without a classification parent is a canonical root unless listed in ``regional``,
    a mapping of each regional genre to its overview: it adds the ``regional_membership`` edge, which
    makes a node regional.
    """
    node_overrides = node_overrides or {}
    regional = regional or {}
    relations = [
        *((child, parent, "classification") for child, parent in classifications),
        *relations,
        *((genre, overview, "regional_membership") for genre, overview in regional.items()),
    ]

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
            **node_overrides.get(genre, {}),
        }
        if node["kind"] == "overview":
            node.update(
                overviewType="current",
                overviewProvenance=provenance(f"overview-{genre.pk}"),
                isUmbrella=True,
            )
        nodes.append(node)
    non_roots = {child for child, _, kind in relations if kind in {"classification", "regional_membership"}}
    roots = [
        genre
        for genre, node in zip(assignments, nodes, strict=True)
        if genre not in non_roots and node["kind"] == "genre"
    ]
    payload = {
        "contractVersion": 4,
        "curationExportedOn": "2026-11-14T00:00:00Z",
        "nodes": nodes,
        "relations": [
            {
                "childId": identity(child),
                "parentId": identity(parent),
                "type": relation_type,
                "provenance": provenance(f"{relation_type}-{identity(child)}-{identity(parent)}"),
            }
            for child, parent, relation_type in relations
        ],
        "canonicalRoots": [
            {"nodeId": identity(genre), "provenance": provenance(f"canonical-root-{genre.pk}")} for genre in roots
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
