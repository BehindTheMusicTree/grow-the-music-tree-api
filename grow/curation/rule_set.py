"""Invariants of the curated rule set as a whole, owned by the API: the pipeline reads them as given.

`find_rule_set_violations` checks a complete state (stored, or stored plus a candidate write). The write paths keep
only the violations touching their own items, so a clash already stored doesn't block an unrelated edit; the export
refuses any."""

from collections.abc import Iterable
from dataclasses import dataclass

from django.db import models

from grow.curation.edges import Relation
from grow.curation.lists import ADDITION_LISTS, EXCLUSIVE_LISTS
from grow.curation.rows import (
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
