from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Value
from django.db.models.functions import Concat

from grow.curation.lists import EDGE_PROJECTION_LISTS
from grow.curation.rows import KEY_SEPARATOR, SCENE_LIST, InvalidRow, UpsertResult, scene_split_error
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.GenreEdgeRule import GenreEdgeRule

Relation = GenreEdgeRule.Relation

PARENT_COLUMN_BY_LIST = {
    "canonical_parent": "parent_item_id",
    "regional_genre_parent": "parent_item_id",
    "regional_overviews": "overview_item_id",
    "secondary_parents": "parent_id",
}
"""Per projected legacy list, the column holding the edge's parent."""

RELATION_BY_LIST = {
    "canonical_parent": Relation.CANONICAL_PARENT,
    "accepted_canonical_roots": Relation.CANONICAL_PARENT,
    "regional_genre_parent": Relation.REGIONAL_GENRE_PARENT,
    "regional_overviews": Relation.REGIONAL_OVERVIEW,
    "secondary_parents": Relation.SECONDARY_PARENT,
}


def edge_rules() -> models.QuerySet[GenreEdgeRule]:
    return GenreEdgeRule.objects.filter(user=None)


def canonical_parents(exclude_pk: Any = None) -> dict[str, str]:
    """Item -> its curated canonical parent, roots left out."""
    rules = edge_rules().filter(relation=Relation.CANONICAL_PARENT, parent_item_id__isnull=False)
    return dict(rules.exclude(pk=exclude_pk).values_list("item_id", "parent_item_id"))


def find_edge_scene_split_error(item_id: str, parent_item_id: str, exclude_pk: Any = None) -> str | None:
    """Why placing `item_id` directly under `parent_item_id` would break a scene split, if it would."""
    scenes = dict(CurationEntry.objects.filter(user=None, list_name=SCENE_LIST).values_list("key", "values__scene"))
    return scene_split_error(scenes, {**canonical_parents(exclude_pk), item_id: parent_item_id}, item_id)


def find_edge_rules(item_id: str) -> models.QuerySet[GenreEdgeRule]:
    """Edges having `item_id` as their item or their parent."""
    return edge_rules().filter(Q(item_id=item_id) | Q(parent_item_id=item_id))


def find_edge_parent_rule(item_id: str) -> GenreEdgeRule | None:
    """A primary or overview edge moving `item_id`, or moving another item under it, if any."""
    return find_edge_rules(item_id).exclude(relation=Relation.SECONDARY_PARENT).first()


def _legacy_row(list_name: str, rule: GenreEdgeRule) -> dict[str, str]:
    columns = EDGE_PROJECTION_LISTS[list_name].columns
    parent_column = PARENT_COLUMN_BY_LIST.get(list_name)
    fields: dict[str, Any] = {
        "item_id": rule.item_id,
        "reason": rule.reason,
        "exclude_other_parents": "true" if rule.exclude_other_parents else "",
        "action": rule.action,
    }
    if parent_column:
        fields[parent_column] = rule.parent_item_id
    return {c: fields[c] for c in columns}


def edge_csv_row(rule: GenreEdgeRule) -> dict[str, str]:
    """The rule as a `genre_edges.csv` row: booleans as "true"/"", no value as ""."""
    return {
        "relation": rule.relation,
        "item_id": rule.item_id,
        "parent_item_id": rule.parent_item_id or "",
        "action": rule.action or "",
        "exclude_other_parents": "true" if rule.exclude_other_parents else "",
        "reason": rule.reason,
    }


def _key(rule_list: str) -> Any:
    if rule_list in {"accepted_canonical_roots", "canonical_parent", "regional_genre_parent"}:
        return models.F("item_id")
    return Concat("item_id", Value(KEY_SEPARATOR), "parent_item_id", output_field=models.CharField())


def project_legacy_lists() -> dict[str, list[dict[str, str]]]:
    """The five legacy curation lists, rebuilt from the edges in the stored lists' exact CSV rows and key order."""
    rules = edge_rules()
    selections: dict[str, models.QuerySet[GenreEdgeRule]] = {
        "canonical_parent": rules.filter(relation=Relation.CANONICAL_PARENT, parent_item_id__isnull=False),
        "accepted_canonical_roots": rules.filter(relation=Relation.CANONICAL_PARENT, parent_item_id__isnull=True),
        "regional_genre_parent": rules.filter(relation=Relation.REGIONAL_GENRE_PARENT),
        "regional_overviews": rules.filter(relation=Relation.REGIONAL_OVERVIEW),
        "secondary_parents": rules.filter(relation=Relation.SECONDARY_PARENT),
    }
    return {
        list_name: [
            _legacy_row(list_name, rule) for rule in queryset.annotate(sort_key=_key(list_name)).order_by("sort_key")
        ]
        for list_name, queryset in selections.items()
    }


def legacy_list_name(rule: GenreEdgeRule) -> str:
    """The legacy list `project_legacy_lists` puts the rule in."""
    if rule.relation == Relation.CANONICAL_PARENT:
        return "accepted_canonical_roots" if rule.parent_item_id is None else "canonical_parent"
    return {
        Relation.REGIONAL_GENRE_PARENT: "regional_genre_parent",
        Relation.REGIONAL_OVERVIEW: "regional_overviews",
        Relation.SECONDARY_PARENT: "secondary_parents",
    }[rule.relation]


def legacy_key(rule: GenreEdgeRule) -> str:
    if legacy_list_name(rule) in {"regional_overviews", "secondary_parents"}:
        return KEY_SEPARATOR.join((rule.item_id, rule.parent_item_id or ""))
    return rule.item_id


def find_rule_by_legacy(list_name: str, key: str) -> GenreEdgeRule | None:
    """The rule a legacy `(list, key)` designates."""
    item_id, _, parent_item_id = key.partition(KEY_SEPARATOR)
    rules = edge_rules().filter(relation=RELATION_BY_LIST[list_name], item_id=item_id)
    if list_name in {"regional_overviews", "secondary_parents"}:
        return rules.filter(parent_item_id=parent_item_id).first()
    if list_name == "accepted_canonical_roots":
        return rules.filter(parent_item_id__isnull=True).first()
    return rules.filter(parent_item_id__isnull=False).first()


def edge_field(column: str) -> str:
    """The `GenreEdgeRule` field a pipeline-reported column (legacy or edge) refers to."""
    return "item_id" if column == "item_id" else "parent_item_id"


def _exclude_value(relation: str, exclude: str) -> bool | None:
    """An empty cell is `false` on the relations that carry the flag and null on `secondary_parent`."""
    if relation == "secondary_parent":
        return None if exclude == "" else exclude == "true"
    return exclude == "true"


def upsert_edge_row(row: dict[str, Any]) -> UpsertResult:
    """Upserts a `genre_edges.csv` row as a canonical rule, recording history. Raises `InvalidRow`."""
    exclude = (row["exclude_other_parents"] or "").strip().lower()
    if exclude not in ("", "true", "false"):
        raise InvalidRow({"exclude_other_parents": "Must be true, false or empty"})
    try:
        return GenreEdgeRule.objects.upsert(
            row["relation"],
            row["item_id"],
            row["parent_item_id"] or None,
            action=row["action"] or None,
            exclude_other_parents=_exclude_value(row["relation"], exclude),
            reason=row["reason"],
        )
    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "error_dict") else {"edge": e.messages}
        raise InvalidRow({field: "; ".join(messages) for field, messages in errors.items()}) from e
