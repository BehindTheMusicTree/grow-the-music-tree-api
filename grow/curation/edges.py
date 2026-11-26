from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from the_music_tree_grow_contracts.curation_lists import EDGE_ACTIONS, EDGE_COLUMNS, EDGE_RELATIONS

from grow.curation.rows import SCENE_LIST, InvalidRow, UpsertResult, scene_split_error
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.GenreEdgeRule import GenreEdgeRule

Relation = GenreEdgeRule.Relation
Action = GenreEdgeRule.Action

RULE_ITEM_COLUMNS = ("item_id", "target_item_id")


def edge_rules() -> models.QuerySet[GenreEdgeRule]:
    return GenreEdgeRule.objects.filter(user=None)


def classification_asserts() -> models.QuerySet[GenreEdgeRule]:
    return edge_rules().filter(relation=Relation.CLASSIFICATION, action=Action.ASSERT)


def global_parents(exclude_pk: Any = None) -> dict[str, str]:
    """Item -> its curated global parent."""
    from grow.curation.rule_set import global_parent_map

    entries = CurationEntry.objects.filter(user=None)
    return global_parent_map(entries, classification_asserts().exclude(pk=exclude_pk))


def find_edge_scene_split_error(item_id: str, target_item_id: str, exclude_pk: Any = None) -> str | None:
    """Why placing `item_id` directly under `target_item_id` would break a scene split, if it would."""
    scenes = dict(CurationEntry.objects.filter(user=None, list_name=SCENE_LIST).values_list("key", "values__scene"))
    return scene_split_error(scenes, {**global_parents(exclude_pk), item_id: target_item_id}, item_id)


def find_edge_rules(item_id: str) -> models.QuerySet[GenreEdgeRule]:
    """Edges having `item_id` as their item or their target."""
    return edge_rules().filter(Q(item_id=item_id) | Q(target_item_id=item_id))


def find_edge_parent_rule(item_id: str) -> GenreEdgeRule | None:
    """The rule placing `item_id` under a global genre, if any."""
    from grow.curation.rule_set import known_global_genres

    rules = list(classification_asserts().filter(item_id=item_id).order_by("target_item_id"))
    global_ids = known_global_genres(CurationEntry.objects.filter(user=None), {r.target_item_id for r in rules})
    return next((r for r in rules if r.target_item_id in global_ids), None)


def edge_csv_row(rule: GenreEdgeRule) -> dict[str, str]:
    """The rule as a `genre_edges.csv` row."""
    return {column: getattr(rule, column) for column in EDGE_COLUMNS}


def edge_field(column: str) -> str:
    """The `GenreEdgeRule` field a pipeline-reported column refers to."""
    if column not in RULE_ITEM_COLUMNS:
        raise InvalidRow({"column": f"{column} is not an item column of a genre edge"})
    return column


def upsert_edge_row(row: dict[str, Any]) -> UpsertResult:
    """Upserts a `genre_edges.csv` row as a canonical rule, recording history. Raises `InvalidRow`."""
    try:
        return GenreEdgeRule.objects.upsert(
            row["relation"],
            row["item_id"],
            row["target_item_id"],
            action=row["action"],
            reason=row["reason"],
            decision_id=row["decision_id"] or None,
        )
    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "error_dict") else {"edge": e.messages}
        raise InvalidRow({field: "; ".join(messages) for field, messages in errors.items()}) from e


def find_edge_candidate_error(
    relation: str, item_id: str, target_item_id: str, action: str, exclude_pk: Any = None
) -> tuple[str, str] | None:
    """The `(field, message)` of the first rule-set violation a rule would add to the stored edges, if any."""
    from grow.curation.rule_set import (
        declared_edge_items,
        excluded_items,
        find_classification_cycles,
        find_edge_kind_violations,
        find_excluded_edge_conflicts,
        find_root_parent_conflicts,
        find_second_global_parents,
        find_undeclared_local_edges,
        global_root_items,
        involving,
        known_kinds,
    )

    if relation not in EDGE_RELATIONS:
        return "relation", "Unknown relation"
    if action not in EDGE_ACTIONS:
        return "action", "Unknown action"
    candidate = GenreEdgeRule(
        user=None, relation=relation, item_id=item_id, target_item_id=target_item_id, action=action
    )
    entries = CurationEntry.objects.filter(user=None)
    others = edge_rules().exclude(pk=exclude_pk)
    items = {item_id, target_item_id}
    kinds = known_kinds(entries, items)
    kind_violations = find_edge_kind_violations(kinds, [candidate])
    if kind_violations:
        return "target_item_id", kind_violations[0].message
    if relation == Relation.CLASSIFICATION and action == Action.ASSERT:
        violations = find_second_global_parents(entries, [*others.filter(item_id=item_id), candidate])
        violations += involving(find_classification_cycles([*others, candidate]), {item_id})
        if violations:
            return "target_item_id", violations[0].message
        if kinds.get(target_item_id) != "overview":
            split_error = find_edge_scene_split_error(item_id, target_item_id, exclude_pk)
            if split_error:
                return "target_item_id", split_error
    violations = find_root_parent_conflicts(global_root_items(entries), entries, [candidate])
    violations += find_excluded_edge_conflicts(excluded_items(entries), [candidate])
    violations += involving(find_undeclared_local_edges(declared_edge_items(entries), [candidate]), items)
    return ("item_id", violations[0].message) if violations else None
