"""Invariants of the curated rule set as a whole, owned by the API: the pipeline reads them as given.

`find_rule_set_violations` checks a complete state (stored, or stored plus a candidate write). The write paths keep
only the violations touching their own items, so a clash already stored doesn't block an unrelated edit; the export
refuses any."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.db import models
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName
from the_music_tree_grow_contracts.curation_lists import (
    ADDITION_LISTS,
    CURATION_LISTS,
    DECISION_ID_COLUMN,
    EXCLUSIVE_LISTS,
    GRAPH_LISTS,
    ITEM_ID_COLUMNS,
)

from grow.curation.edges import Action, Relation
from grow.curation.local_genres import GENERATED_OVERVIEW_PREFIX, ROOTS, is_declared_local_item, placed_items
from grow.curation.rows import (
    KEY_SEPARATOR,
    POP_SIDE_LIST,
    SCENE_LIST,
    find_exclusivity_conflict,
    find_other_pop_child_error,
    find_precedence_cycle,
    precedence_cycle_error,
    scene_split_error,
)
from grow.model.curation.GenreEdgeRule import GenreEdgeRule

LOCAL_PREFIX = "LOCAL:"

GLOBAL_GENRE_LISTS = ("global_roots", "global_parent_additions", "forced_global_genres", "global_genre_scene")
"""Curation lists whose items are global genres, imported or not."""

OVERVIEW_LISTS = ("overview_reclassifications", "regional_overview_additions", "regional_overview_types")
"""Curation lists whose keys are regional overviews."""


@dataclass(frozen=True)
class Violation:
    kind: str
    message: str
    items: frozenset[str]


def known_kinds(entries: models.QuerySet, items: Iterable[str]) -> dict[str, str]:
    """Item -> "genre" or "overview", for the items the reference graph or the curation says something about. An item
    absent from the result is unknown (not imported yet): kind checks let it pass, the pipeline's own checks apply."""
    from the_music_tree_genre_kit.genre_graph.models import GenreGraphNode

    from grow.genre_graph.service import DATASET_KEY

    items = set(items)
    nodes = GenreGraphNode.objects.filter(dataset_id=DATASET_KEY, is_active=True, identity__in=items)
    kinds = {i: "overview" if state is None else "genre" for i, state in nodes.values_list("identity", "state")}
    kinds.update(dict.fromkeys(known_global_genres(entries, items), "genre"))
    kinds.update(
        dict.fromkeys(
            entries.filter(list_name__in=OVERVIEW_LISTS, key__in=items).values_list("key", flat=True), "overview"
        )
    )
    anchors = entries.filter(list_name="regional_anchorings", values__overview_item_id__in=items)
    kinds.update(dict.fromkeys((e.values["overview_item_id"] for e in anchors), "overview"))
    identities = entries.filter(list_name="local_identities", key__in=items)
    kinds.update({e.key: e.values["kind"] for e in identities})
    kinds.update(dict.fromkeys((i for i in items if i.startswith(GENERATED_OVERVIEW_PREFIX)), "overview"))
    return kinds


def known_global_genres(entries: models.QuerySet, items: Iterable[str]) -> set[str]:
    """The items among `items` that are global genres, in the live tree or in a global curation list."""
    from grow.model.criteria.children.genre.Genre import Genre

    items = set(items)
    genres = Genre.objects.filter(user=None, tree_name=CriteriaTreeName.GLOBAL, wikidata_id__in=items)
    listed = entries.filter(list_name__in=GLOBAL_GENRE_LISTS, key__in=items)
    return set(genres.values_list("wikidata_id", flat=True)) | set(listed.values_list("key", flat=True))


def _classification_asserts(edges: Iterable[GenreEdgeRule]) -> list[GenreEdgeRule]:
    return [e for e in edges if e.relation == Relation.CLASSIFICATION and e.action == Action.ASSERT]


def global_parent_map(entries: models.QuerySet, edges: Iterable[GenreEdgeRule]) -> dict[str, str]:
    """Item -> the global genre a classification assert places it under."""
    asserts = _classification_asserts(edges)
    global_ids = known_global_genres(entries, {e.target_item_id for e in asserts})
    return {e.item_id: e.target_item_id for e in asserts if e.target_item_id in global_ids}


def global_root_items(entries: models.QuerySet) -> set[str]:
    return set(entries.filter(list_name="global_roots").values_list("key", flat=True))


def find_root_parent_conflicts(
    roots: set[str], entries: models.QuerySet, edges: Iterable[GenreEdgeRule]
) -> list[Violation]:
    """An accepted global root that a rule also classifies under a genre: it is a root or a child, not both."""
    asserts = [e for e in _classification_asserts(edges) if e.item_id in roots]
    kinds = known_kinds(entries, {e.target_item_id for e in asserts})
    parented = sorted({e.item_id for e in asserts if kinds.get(e.target_item_id) != "overview"})
    return [
        Violation(
            "root_parent", f"{item} is an accepted global root and is also classified under a genre", frozenset({item})
        )
        for item in parented
    ]


def find_second_global_parents(entries: models.QuerySet, edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    """An item that classification asserts place under several global genres: a genre has at most one."""
    asserts = _classification_asserts(edges)
    global_ids = known_global_genres(entries, {e.target_item_id for e in asserts})
    parents: dict[str, set[str]] = {}
    for edge in asserts:
        if edge.target_item_id in global_ids:
            parents.setdefault(edge.item_id, set()).add(edge.target_item_id)
    return [
        Violation(
            "second_global_parent",
            f"{item} has several global parents ({', '.join(sorted(targets))}); a genre has at most one",
            frozenset({item, *targets}),
        )
        for item, targets in sorted(parents.items())
        if len(targets) > 1
    ]


def find_edge_kind_violations(kinds: dict[str, str], edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    """A rule whose relation doesn't fit the kinds of its ends: derivations and influences link genres, and an
    overview is never classified under a genre."""
    violations = []
    for edge in edges:
        triplet = f"{edge.relation} {edge.item_id} -> {edge.target_item_id}"
        ends = (edge.item_id, edge.target_item_id)
        if edge.relation != Relation.CLASSIFICATION:
            violations.extend(
                Violation(
                    "local_kind", f"{item} is an overview, so it can't be an end of the {triplet} rule", frozenset(ends)
                )
                for item in ends
                if kinds.get(item) == "overview"
            )
        elif kinds.get(edge.item_id) == "overview" and kinds.get(edge.target_item_id) == "genre":
            violations.append(
                Violation(
                    "local_kind",
                    f"{edge.item_id} is an overview, and an overview is never classified under a genre ({triplet})",
                    frozenset(ends),
                )
            )
    return violations


def find_classification_cycles(edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    parents: dict[str, list[str]] = {}
    for edge in _classification_asserts(edges):
        parents.setdefault(edge.item_id, []).append(edge.target_item_id)
    violations, done = [], set()
    for start in sorted(parents):
        if start in done:
            continue
        # Iterative: a classification chain has no bounded depth.
        path, stack = [start], [iter(sorted(parents[start]))]
        while stack:
            parent = next(stack[-1], None)
            if parent is None:
                stack.pop()
                done.add(path.pop())
            elif parent in path:
                cycle = path[path.index(parent) :]
                violations.append(
                    Violation(
                        "classification_cycle",
                        "Classification rules form the cycle " + " -> ".join([*cycle, parent]),
                        frozenset(cycle),
                    )
                )
            elif parent not in done:
                path.append(parent)
                stack.append(iter(sorted(parents.get(parent, []))))
    return violations


def find_excluded_edge_conflicts(excluded: dict[str, str], edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    """An edge placing an item that a pruning list excludes, or placing one under it: the rule can't apply to a
    pruned genre."""
    violations = []
    for edge in edges:
        if edge.action == Action.PROHIBIT:
            continue
        for item in dict.fromkeys((edge.item_id, edge.target_item_id)):
            if item in excluded:
                violations.append(
                    Violation(
                        "excluded_edge",
                        f"{item} is in {excluded[item]} but has the {edge.relation} rule "
                        f"{edge.item_id} -> {edge.target_item_id}",
                        frozenset({edge.item_id, item}),
                    )
                )
    return violations


def excluded_items(entries: models.QuerySet) -> dict[str, str]:
    return dict(entries.filter(list_name__in=EXCLUSIVE_LISTS).values_list("key", "list_name"))


def declared_additions(entries: models.QuerySet) -> set[str]:
    """Items the pipeline injects as synthetic nodes before it applies the edge rules."""
    return set(entries.filter(list_name__in=ADDITION_LISTS).values_list("key", flat=True))


def declared_edge_items(entries: models.QuerySet) -> set[str]:
    """The `LOCAL:` items an edge may name: the additions and the local identities."""
    identities = entries.filter(list_name="local_identities").values_list("key", flat=True)
    return declared_additions(entries) | set(identities)


def find_undeclared_local_edges(declared: set[str], edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    """An edge naming a `LOCAL:` item that no addition list nor local identity declares: the pipeline drops such a
    rule silently, and fails the run once too many are dropped."""
    used = {item for e in edges for item in (e.item_id, e.target_item_id) if item.startswith(LOCAL_PREFIX)}
    return [
        Violation(
            "undeclared_local",
            f"{item} is used in an edge but declared in no addition list nor local identity",
            frozenset({item}),
        )
        for item in sorted(used - declared)
    ]


def find_unplaced_local_additions(additions: set[str], placed: set[str]) -> list[Violation]:
    """A global `LOCAL:` addition with neither a classification under a genre nor an accepted root entry: the
    pipeline cannot place the node, and Gold stops emitting it while grow still holds the genre."""
    return [
        Violation(
            "local_addition_unplaced",
            f"{item} is declared in global_parent_additions but has neither a global parent nor a global_roots entry",
            frozenset({item}),
        )
        for item in sorted(additions - placed)
        if is_declared_local_item(item)
    ]


GraphRow = tuple[str, str, dict[str, Any]]
"""A regional graph entry: its list, key and values."""

MERGE_LIST = "genre_merges"
OVERVIEW_COLUMNS = {"regional_anchorings": "overview_item_id", "regional_overview_types": "item_id"}


def graph_row_items(list_name: str, key: str, values: dict[str, Any]) -> dict[str, str]:
    """The item ids of a graph row by column, key columns included."""
    fields = {**dict(zip(CURATION_LISTS[list_name].key, key.split(KEY_SEPARATOR), strict=True)), **values}
    return {c: v for c, v in fields.items() if c in ITEM_ID_COLUMNS and v}


def _find_duplicate_decisions(rows: list[GraphRow]) -> list[Violation]:
    by_decision: dict[str, list[GraphRow]] = {}
    for row in rows:
        by_decision.setdefault(row[2].get(DECISION_ID_COLUMN, ""), []).append(row)
    return [
        Violation(
            "duplicate_decision",
            f"decision {decision} is used by {len(group)} entries: " + ", ".join(f"{n} {k}" for n, k, _ in group),
            frozenset(i for n, k, v in group for i in graph_row_items(n, k, v).values()),
        )
        for decision, group in sorted(by_decision.items())
        if decision and len(group) > 1
    ]


def _find_undeclared_graph_locals(rows: list[GraphRow], kinds: dict[str, str], additions: set[str]) -> list[Violation]:
    def local_items(list_name: str) -> set[str]:
        return {
            i
            for n, k, v in rows
            if n == list_name
            for i in graph_row_items(n, k, v).values()
            if i.startswith(LOCAL_PREFIX)
        }

    used = {
        i
        for n, k, v in rows
        if n not in ("local_identities", MERGE_LIST, "global_roots")
        for i in graph_row_items(n, k, v).values()
        if i.startswith(LOCAL_PREFIX)
    }
    violations = [
        Violation(
            "undeclared_local", f"{item} is used in a regional graph entry but declared in no local identity", {item}
        )
        for item in sorted(used - kinds.keys())
    ]
    # A merge or a root names global nodes, which an addition list declares as often as a local identity does.
    for list_name, usage in ((MERGE_LIST, "a genre merge"), ("global_roots", "the global roots")):
        violations += [
            Violation(
                "undeclared_local",
                f"{item} is used in {usage} but declared in no local identity nor addition list",
                frozenset({item}),
            )
            for item in sorted(local_items(list_name) - kinds.keys() - additions)
        ]
    return violations


def _find_local_kind_violations(rows: list[GraphRow], kinds: dict[str, str]) -> list[Violation]:
    violations = []
    for list_name, key, values in rows:
        column = OVERVIEW_COLUMNS.get(list_name)
        if column is None:
            continue
        item = graph_row_items(list_name, key, values).get(column)
        if item in kinds and kinds[item] != "overview":
            violations.append(
                Violation(
                    "local_kind",
                    f"{item} is declared as a {kinds[item]} but is the {column} of {list_name} {key}: "
                    "it must be an overview",
                    frozenset({item}),
                )
            )
    return violations


def find_graph_violations(rows: list[GraphRow], additions: set[str]) -> list[Violation]:
    """Invariants of the regional graph decisions together. Grow can't check that a QID exists nor the global
    state, which the pipeline computes: the pipeline and the genre kit's `GenreGraph` reject unknown QIDs and
    classification cycles. `additions` are the items the addition lists declare."""
    kinds = {k: v.get("kind", "") for n, k, v in rows if n == "local_identities"}
    return [
        *_find_duplicate_decisions(rows),
        *_find_undeclared_graph_locals(rows, kinds, additions),
        *_find_local_kind_violations(rows, kinds),
    ]


def find_scene_split_violations(entries: models.QuerySet, edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    scenes = dict(entries.filter(list_name=SCENE_LIST).values_list("key", "values__scene"))
    parents = global_parent_map(entries, edges)
    violations, seen = [], set()
    for item in sorted(parents):
        message = scene_split_error(scenes, parents, item)
        if message and message not in seen:
            seen.add(message)
            violations.append(Violation("scene_split", message, frozenset({item, parents[item]})))
    return violations


def find_rule_set_violations(entries: models.QuerySet, edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    """Every invariant the stored curation entries and `edges` break together, in a stable order.

    The umbrella-leaf check reads the live Genre tree, itself built from the export, so it stays on the write path:
    gating the export on it could leave no way to publish a fresh tree."""
    edges = list(edges)
    violations: list[Violation] = []
    lists_by_item: dict[str, list[str]] = {}
    for list_name, key in entries.filter(list_name__in=EXCLUSIVE_LISTS).order_by("key").values_list("list_name", "key"):
        lists_by_item.setdefault(key, []).append(list_name)
    for key, list_names in lists_by_item.items():
        if len(list_names) > 1:
            violations.append(
                Violation(
                    "exclusivity",
                    f"{key} is in {' and '.join(sorted(list_names))}; these lists are mutually exclusive",
                    {key},
                )
            )
    for key in entries.filter(list_name="genre_precedence").order_by("key").values_list("key", flat=True):
        cycle = find_precedence_cycle(entries, "genre_precedence", key)
        if cycle:
            violations.append(Violation("precedence_cycle", precedence_cycle_error(cycle), frozenset(cycle)))
    for key in entries.filter(list_name=POP_SIDE_LIST).order_by("key").values_list("key", flat=True):
        message = find_other_pop_child_error(entries, POP_SIDE_LIST, key)
        if message:
            violations.append(Violation("pop_child", message, set(key.split("\t"))))
    violations += find_scene_split_violations(entries, edges)
    violations += find_second_global_parents(entries, edges)
    violations += find_classification_cycles(edges)
    kinds = known_kinds(entries, {item for e in edges for item in (e.item_id, e.target_item_id)})
    violations += find_edge_kind_violations(kinds, edges)
    violations += find_root_parent_conflicts(global_root_items(entries), entries, edges)
    violations += find_excluded_edge_conflicts(excluded_items(entries), edges)
    violations += find_undeclared_local_edges(declared_edge_items(entries), edges)
    violations += find_unplaced_local_additions(
        set(entries.filter(list_name="global_parent_additions").values_list("key", flat=True)),
        placed_items({ROOTS: global_root_items(entries)}, edges),
    )
    graph_rows = entries.filter(list_name__in=GRAPH_LISTS).order_by("list_name", "key")
    violations += find_graph_violations(
        [(e.list_name, e.key, e.values) for e in graph_rows], declared_additions(entries)
    )
    return [Violation(v.kind, v.message, frozenset(v.items)) for v in violations]


def involving(violations: Iterable[Violation], items: Iterable[str]) -> list[Violation]:
    """The violations touching any of `items`."""
    items = set(items)
    return [v for v in violations if v.items & items]


def find_stored_violations() -> list[Violation]:
    """The violations of the canonical entries and edges as stored."""
    from grow.curation.edges import edge_rules
    from grow.model.curation.CurationEntry import CurationEntry

    return find_rule_set_violations(CurationEntry.objects.filter(user=None), edge_rules())
