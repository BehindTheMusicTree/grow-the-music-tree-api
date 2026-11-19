"""Invariants of the curated rule set as a whole, owned by the API: the pipeline reads them as given.

`find_rule_set_violations` checks a complete state (stored, or stored plus a candidate write). The write paths keep
only the violations touching their own items, so a clash already stored doesn't block an unrelated edit; the export
refuses any."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.db import models

from grow.curation.edges import Relation
from grow.curation.lists import (
    ADDITION_LISTS,
    CURATION_LISTS,
    DECISION_ID_COLUMN,
    EXCLUSIVE_LISTS,
    GRAPH_LISTS,
    ITEM_ID_COLUMNS,
)
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

REGIONAL_RELATIONS = (Relation.REGIONAL_GENRE_PARENT, Relation.REGIONAL_OVERVIEW)


@dataclass(frozen=True)
class Violation:
    kind: str
    message: str
    items: frozenset[str]


def find_root_regional_conflicts(edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    """An accepted canonical root that also has a regional parent or overview rule: the root pins it out of the
    regional axis the rule places it in."""
    edges = list(edges)
    roots = {e.item_id for e in edges if e.relation == Relation.CANONICAL_PARENT and e.parent_item_id is None}
    regional = sorted({e.item_id for e in edges if e.relation in REGIONAL_RELATIONS} & roots)
    return [
        Violation("root_regional", f"{item} is an accepted canonical root and also has a regional rule", {item})
        for item in regional
    ]


def find_excluded_edge_conflicts(excluded: dict[str, str], edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    """An edge placing an item that a pruning list excludes: the rule can't apply to a pruned genre."""
    return [
        Violation(
            "excluded_edge",
            f"{edge.item_id} is in {excluded[edge.item_id]} but has the {edge.relation} rule "
            f"{edge.item_id} -> {edge.parent_item_id}",
            {edge.item_id},
        )
        for edge in edges
        if edge.item_id in excluded and edge.parent_item_id is not None and edge.action != GenreEdgeRule.Action.REMOVE
    ]


def excluded_items(entries: models.QuerySet) -> dict[str, str]:
    return dict(entries.filter(list_name__in=EXCLUSIVE_LISTS).values_list("key", "list_name"))


def declared_additions(entries: models.QuerySet) -> set[str]:
    """Items the pipeline injects as synthetic nodes before it applies the edge rules."""
    return set(entries.filter(list_name__in=ADDITION_LISTS).values_list("key", flat=True))


def find_undeclared_local_edges(declared: set[str], edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    """An edge naming a `LOCAL:` item that no addition list declares: the pipeline drops such a rule silently, and
    fails the run once too many are dropped."""
    used = {
        item for e in edges for item in (e.item_id, e.parent_item_id) if item is not None and item.startswith("LOCAL:")
    }
    return [
        Violation("undeclared_local", f"{item} is used in an edge but declared in no addition list", {item})
        for item in sorted(used - declared)
    ]


GraphRow = tuple[str, str, dict[str, Any]]
"""A regional graph entry: its list, key and values."""

LOCAL_PREFIX = "LOCAL:"
MEMBERSHIP_LIST = "regional_memberships"
LOCAL_KIND_ROLES: tuple[tuple[str, str, str], ...] = (
    ("regional_anchorings", "overview_item_id", "overview"),
    ("regional_overview_types", "item_id", "overview"),
    (MEMBERSHIP_LIST, "parent_item_id", "overview"),
    ("expression_styles", "expression_item_id", "expression"),
)
"""(list, column, kind) a `LOCAL:` id used in that column must be declared as."""


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


def _find_undeclared_graph_locals(rows: list[GraphRow], kinds: dict[str, str]) -> list[Violation]:
    used = {
        i
        for n, k, v in rows
        if n != "local_identities"
        for i in graph_row_items(n, k, v).values()
        if i.startswith(LOCAL_PREFIX)
    }
    return [
        Violation(
            "undeclared_local", f"{item} is used in a regional graph entry but declared in no local identity", {item}
        )
        for item in sorted(used - kinds.keys())
    ]


def _find_local_kind_violations(rows: list[GraphRow], kinds: dict[str, str]) -> list[Violation]:
    violations = []
    for list_name, key, values in rows:
        items = graph_row_items(list_name, key, values)
        for role_list, column, kind in LOCAL_KIND_ROLES:
            item = items.get(column)
            if list_name == role_list and item in kinds and kinds[item] != kind:
                violations.append(
                    Violation(
                        "local_kind",
                        f"{item} is declared as a {kinds[item]} but is the {column} of {list_name} {key}: "
                        f"it must be an {kind}",
                        {item},
                    )
                )
        style = items.get("style_item_id")
        if list_name == "expression_styles" and kinds.get(style) == "overview":
            violations.append(
                Violation("local_kind", f"{style} is an overview, so it can't be the style of {key}", {style})
            )
    return violations


def _find_membership_cycles(rows: list[GraphRow]) -> list[Violation]:
    parents: dict[str, list[str]] = {}
    for list_name, key, values in rows:
        if list_name == MEMBERSHIP_LIST and values.get("action") == "add":
            child, parent = key.split(KEY_SEPARATOR)
            parents.setdefault(child, []).append(parent)
    violations, done = [], set()

    def visit(node: str, path: list[str]) -> None:
        if node in path:
            cycle = path[path.index(node) :]
            violations.append(
                Violation(
                    "membership_cycle",
                    "Regional memberships form the cycle " + " -> ".join([*cycle, node]),
                    frozenset(cycle),
                )
            )
            return
        if node in done:
            return
        for parent in sorted(parents.get(node, [])):
            visit(parent, [*path, node])
        done.add(node)

    for child in sorted(parents):
        visit(child, [])
    return violations


def find_graph_violations(rows: list[GraphRow]) -> list[Violation]:
    """Invariants of the regional graph decisions together. Grow can't check that a QID exists nor the canonical
    state, which the pipeline computes: the pipeline and the genre kit's `GenreGraph` reject unknown QIDs and
    classification cycles."""
    kinds = {k: v.get("kind", "") for n, k, v in rows if n == "local_identities"}
    return [
        *_find_duplicate_decisions(rows),
        *_find_undeclared_graph_locals(rows, kinds),
        *_find_local_kind_violations(rows, kinds),
        *_find_membership_cycles(rows),
    ]


def find_scene_split_violations(entries: models.QuerySet, edges: Iterable[GenreEdgeRule]) -> list[Violation]:
    scenes = dict(entries.filter(list_name=SCENE_LIST).values_list("key", "values__scene"))
    parents = {
        e.item_id: e.parent_item_id for e in edges if e.relation == Relation.CANONICAL_PARENT and e.parent_item_id
    }
    violations, seen = [], set()
    for item in sorted(parents):
        message = scene_split_error(scenes, parents, item)
        if message and message not in seen:
            seen.add(message)
            violations.append(Violation("scene_split", message, {item, parents[item]}))
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
    violations += find_root_regional_conflicts(edges)
    violations += find_excluded_edge_conflicts(excluded_items(entries), edges)
    violations += find_undeclared_local_edges(declared_additions(entries), edges)
    graph_rows = entries.filter(list_name__in=GRAPH_LISTS).order_by("list_name", "key")
    violations += find_graph_violations([(e.list_name, e.key, e.values) for e in graph_rows])
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
