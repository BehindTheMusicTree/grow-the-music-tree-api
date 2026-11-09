"""What 0036 needs of the curation helpers, frozen so it never depends on the current curation registry (the parent
lists it writes later moved to `GenreEdgeRule`, see 0112)."""

from django.db.models import Q
from django.utils import timezone

EXCLUSIVE_LISTS = frozenset({"theme_genres", "technique_genres", "out_of_scope_genres", "duplicate_genres"})
PARENT_RULE_COLUMNS = {
    "canonical_parent": "parent_item_id",
    "regional_genre_parent": "parent_item_id",
    "regional_overviews": "overview_item_id",
}
KEY_SEPARATOR = "\t"
BOOL_COLUMNS = frozenset({"exclude_other_parents"})
COLUMNS = {
    "accepted_canonical_roots": ("item_id",),
    "canonical_parent": ("item_id", "reason", "parent_item_id", "exclude_other_parents"),
    "label_overrides": ("item_id", "display_label", "reason"),
    "out_of_scope_genres": ("item_id", "reason"),
}


def find_parent_rule(entries, item_id: str):
    """A parent-rule entry moving `item_id`, or moving another item under it, if any."""
    for list_name, column in PARENT_RULE_COLUMNS.items():
        query = Q(key=item_id) | Q(key__startswith=item_id + KEY_SEPARATOR) | Q(**{f"values__{column}": item_id})
        found = entries.filter(query, list_name=list_name).first()
        if found is not None:
            return found
    return None


def upsert_without_history(model, list_name: str, row: dict) -> str:
    columns = COLUMNS[list_name]
    unknown = set(row) - set(columns)
    if unknown:
        raise ValueError(f"{list_name}: unknown columns {sorted(unknown)}")
    key = row["item_id"]
    values = {}
    for column in columns:
        if column in ("item_id", "reason"):
            continue
        value = row.get(column, "")
        values[column] = (str(value).lower() == "true") if column in BOOL_COLUMNS else value
    fields = {"values": values, "reason": row.get("reason", "")}
    entries = model.objects.filter(user=None)
    entry = entries.filter(list_name=list_name, key=key).first()
    if entry is None:
        model.objects.create(user=None, list_name=list_name, key=key, **fields)
        return "created"
    if all(getattr(entry, k) == v for k, v in fields.items()):
        return "unchanged"
    entries.filter(pk=entry.pk).update(updated_on=timezone.now(), **fields)
    return "updated"
