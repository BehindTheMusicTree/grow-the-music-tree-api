"""Seed helpers shared by perf/conftest.py and scripts/seed_dev_db.py (pure Python, no Django).

The pinned Gold exports predate any producer of a v2 reference graph or of reviewed song assignments, so
this module derives both from the Gold trees. The conversion is approximate (regional placement,
primaryParents, groupings and scene splits are flattened into classification edges, no polygenre): replace
it with the Gold graph export and exports carrying assignments once the pipelines produce them.
"""

import gzip
import json
from collections import defaultdict
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
TREES = ["1_canonical_genre_tree.json.gz", "1_regional_genre_tree.json.gz"]
SONGS = "2_songs.json.gz"
SOURCE = "fixture:perf-gold-trees"

# Gold song exports naming a genre that no Gold tree contains. Pinned exactly: a new anomaly, or one that
# disappears after a re-pin, fails the seed instead of silently changing the measured data.
UNRESOLVED_GENRE_NAMES = {"deathcore": 5}


def load_trees(exported_on: str) -> list[dict]:
    trees = []
    for fixture in TREES:
        with gzip.open(FIXTURES / fixture) as file:
            trees.append({**json.load(file), "curationExportedOn": exported_on})
    return trees


def load_songs() -> list[dict]:
    with gzip.open(FIXTURES / SONGS) as file:
        return json.load(file)


def _provenance(decision: str, rationale: str) -> dict:
    return {"decisionId": decision, "source": SOURCE, "rationale": rationale}


def _walk(nodes: list[dict], tree: str, parent: str | None, out: list[tuple[str, dict, str | None]]) -> None:
    for node in nodes:
        out.append((tree, node, parent))
        _walk(node["children"], tree, node["id"], out)


def flatten(trees: list[dict]) -> list[tuple[str, dict, str | None]]:
    """(tree name, Gold node, nesting parent id) for every node."""
    flat: list[tuple[str, dict, str | None]] = []
    for tree in trees:
        _walk(tree["tree"], tree["treeName"], None, flat)
    return flat


def build_graph(trees: list[dict]) -> dict:
    flat = flatten(trees)
    ids = {node["id"] for _, node, _ in flat}
    if len(ids) != len(flat):
        raise ValueError("Gold trees share a node id")
    parents: dict[str, list[str]] = {}
    display: dict[str, str] = {}
    for _, node, nesting in flat:
        accepted = [nesting] if nesting else []
        accepted += [p for p in node.get("primaryParents", []) if p in ids and p not in accepted and p != node["id"]]
        parents[node["id"]] = accepted
        if accepted:
            display[node["id"]] = accepted[0]
    relations = [
        {
            "childId": child,
            "parentId": parent,
            "type": "classification",
            "provenance": _provenance(f"classification-{child}-{parent}", "Gold tree edge, approximate conversion."),
        }
        for child, accepted in parents.items()
        for parent in accepted
    ]
    roots = [child for child, accepted in parents.items() if not accepted]
    return {
        "contractVersion": 2,
        "curationExportedOn": trees[0]["curationExportedOn"],
        "nodes": [
            {
                "id": node["id"],
                "name": node["name"],
                "kind": "genre",
                "canonicalState": "canonical",
                **({"displayParentId": display[node["id"]]} if node["id"] in display else {}),
            }
            for _, node, _ in flat
        ],
        "relations": relations,
        "boundaries": [
            {"nodeId": root, "type": "entry", "provenance": _provenance(f"entry-{root}", "Gold tree root.")}
            for root in roots
        ],
    }


def identity_mapping(graph: dict, genres: list[dict]) -> dict[str, str | None]:
    """Gold id → genre UUID through Genre.wikidata_id (which stores the Gold id), never by label."""
    by_gold_id = {genre["wikidata_id"]: genre["uuid"] for genre in genres if genre.get("wikidata_id")}
    mapping = {node["id"]: by_gold_id.get(node["id"]) for node in graph["nodes"]}
    missing = [identity for identity, pk in mapping.items() if pk is None]
    if missing:
        raise ValueError(f"{len(missing)} Gold nodes have no imported genre, e.g. {missing[:5]}")
    return mapping


def resolve_songs(trees: list[dict], songs: list[dict]) -> dict[str, str | None]:
    """musicbrainz_recording_id → Gold id. The canonical tree wins over the regional one; a name that is
    ambiguous inside one tree, or absent from both, is an error unless pinned in UNRESOLVED_GENRE_NAMES."""
    by_tree: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for tree, node, _ in flatten(trees):
        by_tree[tree][node["name"].lower()].append(node["id"])
    order = sorted(by_tree, key=lambda tree: tree != "canonical")
    resolved: dict[str, str | None] = {}
    unresolved: dict[str, int] = defaultdict(int)
    for song in songs:
        name = song.get("genre_name")
        if not name:
            resolved[song["musicbrainz_recording_id"]] = None
            continue
        for tree in order:
            matches = by_tree[tree].get(name.lower(), [])
            if len(matches) > 1:
                raise ValueError(f"Ambiguous genre name in the {tree} tree: {name!r}")
            if matches:
                resolved[song["musicbrainz_recording_id"]] = matches[0]
                break
        else:
            unresolved[name.lower()] += 1
            resolved[song["musicbrainz_recording_id"]] = None
    if dict(unresolved) != UNRESOLVED_GENRE_NAMES:
        raise ValueError(f"Unresolved genre names {dict(unresolved)} differ from the pinned {UNRESOLVED_GENRE_NAMES}")
    return resolved


def songs_part(songs: list[dict]) -> bytes:
    return gzip.compress("".join(json.dumps({"first_release_year": None, **song}) + "\n" for song in songs).encode())


def assignments_part(resolved: dict[str, str | None]) -> bytes:
    lines = []
    for recording, identity in resolved.items():
        # Every imported song needs a row; one without a resolved genre is imported unassigned.
        evidence = [_provenance(f"song-{recording}", "Gold song export genre_name, approximate conversion.")]
        assignments = {} if identity is None else {identity: evidence}
        lines.append(json.dumps({"musicbrainz_recording_id": recording, "assignments": assignments}) + "\n")
    return gzip.compress("".join(lines).encode())


def read_genres(fetch_page) -> list[dict]:
    """Every ownerless genre as {uuid, wikidata_id}; fetch_page(page) returns one paginated JSON body."""
    genres, page = [], 1
    while True:
        body = fetch_page(page)
        genres += [{"uuid": row["uuid"], "wikidata_id": row.get("wikidataId")} for row in body["results"]]
        if not body["next"]:
            return genres
        page += 1


def run_body(revisions: dict, *, songs: int = 1, assignments: int = 1) -> dict:
    """Reviewed run metadata from the GET genres/graph/ tokens."""
    return {
        "graph_revision": revisions["revision"],
        "membership_revision": revisions["membershipRevision"],
        "expected_parts": {"songs": songs, "assignments": assignments},
    }
