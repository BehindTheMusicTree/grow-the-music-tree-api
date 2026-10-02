import csv
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from django.db import models
from django.utils import timezone

from grow.curation.lists import (
    BOOL_COLUMNS,
    CURATION_LISTS,
    EXCLUSIVE_LISTS,
    ITEM_ID_COLUMNS,
    ITEM_ID_PATTERN,
    KEY_MAX_LENGTH,
    PARENT_RULE_COLUMNS,
)

KEY_SEPARATOR = "\t"
SEED_DIR = Path(__file__).parent / "seed"

UpsertResult = Literal["created", "updated", "unchanged"]


class InvalidRow(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__(errors)
        self.errors = errors


@dataclass(frozen=True)
class ParsedRow:
    key: str
    values: dict[str, Any]
    reason: str


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"", "false"}:
        return False
    if isinstance(value, str) and value.strip().lower() == "true":
        return True
    raise ValueError


def parse_row(list_name: str, row: dict[str, Any]) -> ParsedRow:
    """Validates a row keyed by the list's CSV column names into the entry's stored fields."""
    curation_list = CURATION_LISTS[list_name]
    errors: dict[str, str] = {}
    unknown = set(row) - set(curation_list.columns)
    for column in sorted(unknown):
        errors[column] = "Unknown column"
    parsed: dict[str, Any] = {}
    for column in curation_list.columns:
        value = row.get(column)
        if column in BOOL_COLUMNS:
            try:
                parsed[column] = _parse_bool(value)
            except ValueError:
                errors[column] = "Must be a boolean"
            continue
        if not isinstance(value, str) or not value.strip():
            errors[column] = "Required"
            continue
        if column in curation_list.key and KEY_SEPARATOR in value:
            errors[column] = "Must not contain a tab"
            continue
        if column in ITEM_ID_COLUMNS and not re.fullmatch(ITEM_ID_PATTERN, value):
            errors[column] = "Must be a Wikidata QID (Q123) or a LOCAL:<slug> id"
            continue
        parsed[column] = value
    if errors:
        raise InvalidRow(errors)
    key = KEY_SEPARATOR.join(parsed[c] for c in curation_list.key)
    if len(key) > KEY_MAX_LENGTH:
        raise InvalidRow({curation_list.key[-1]: f"Key must be at most {KEY_MAX_LENGTH} characters"})
    return ParsedRow(
        key=key,
        values={c: parsed[c] for c in curation_list.value_columns},
        reason=parsed.get("reason", ""),
    )


def to_row(list_name: str, key: str, values: dict[str, Any], reason: str) -> dict[str, Any]:
    """The entry back as a row in CSV column order, booleans kept as booleans."""
    curation_list = CURATION_LISTS[list_name]
    fields = {**dict(zip(curation_list.key, key.split(KEY_SEPARATOR), strict=True)), **values, "reason": reason}
    return {c: fields[c] for c in curation_list.columns}


def to_csv_row(list_name: str, key: str, values: dict[str, Any], reason: str) -> dict[str, str]:
    return {
        c: ("true" if v else "") if c in BOOL_COLUMNS else v for c, v in to_row(list_name, key, values, reason).items()
    }


def find_exclusivity_conflict(
    queryset: models.QuerySet, list_name: str, key: str, exclude_pk: Any = None
) -> str | None:
    """The other exclusive list already holding this item_id, if any."""
    if list_name not in EXCLUSIVE_LISTS:
        return None
    others = queryset.filter(list_name__in=EXCLUSIVE_LISTS - {list_name}, key=key).exclude(pk=exclude_pk)
    return others.values_list("list_name", flat=True).first()


def find_item_rules(queryset: models.QuerySet, item_id: str) -> models.QuerySet:
    """Entries referencing `item_id`: as their key, as part of a composite key, or as an item-id value."""
    query = models.Q(key=item_id) | models.Q(key__startswith=item_id + KEY_SEPARATOR)
    query |= models.Q(key__endswith=KEY_SEPARATOR + item_id)
    for column in ITEM_ID_COLUMNS:
        query |= models.Q(**{f"values__{column}": item_id})
    return queryset.filter(query)


def find_parent_rule(queryset: models.QuerySet, item_id: str) -> Any:
    """A `PARENT_RULE_COLUMNS` entry moving `item_id`, or moving another item under it, if any."""
    return find_item_rules(queryset.filter(list_name__in=PARENT_RULE_COLUMNS), item_id).first()


def check_upsert(entries: models.QuerySet, list_name: str, row: dict[str, Any]) -> tuple[ParsedRow, Any]:
    """Validates `row` for an upsert into `entries`: the parsed row, and the entry with its key to update, if any."""
    parsed = parse_row(list_name, row)
    conflict = find_exclusivity_conflict(entries, list_name, parsed.key)
    if conflict:
        raise InvalidRow(
            {
                CURATION_LISTS[list_name].key[
                    0
                ]: f"{parsed.key} is already in {conflict}; these lists are mutually exclusive"
            }
        )
    return parsed, entries.filter(list_name=list_name, key=parsed.key).first()


def upsert_without_history(model: type[models.Model], list_name: str, row: dict[str, Any]) -> UpsertResult:
    """`CurationEntryManager.upsert` for migrations, whose historical models have neither the manager nor history."""
    entries = model.objects.filter(user=None)
    parsed, entry = check_upsert(entries, list_name, row)
    fields = {"values": parsed.values, "reason": parsed.reason}
    if entry is None:
        model.objects.create(user=None, list_name=list_name, key=parsed.key, **fields)
        return "created"
    if all(getattr(entry, k) == v for k, v in fields.items()):
        return "unchanged"
    entries.filter(pk=entry.pk).update(updated_on=timezone.now(), **fields)
    return "updated"


def import_csv_dir(directory: Path, upsert: Callable[[str, dict[str, Any]], UpsertResult]) -> Counter[UpsertResult]:
    """Upserts every list from `manual_<list_name>.csv` in `directory`. Returns the count of each upsert result."""
    results: Counter[UpsertResult] = Counter()
    for list_name, curation_list in CURATION_LISTS.items():
        path = directory / f"manual_{list_name}.csv"
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if tuple(reader.fieldnames or ()) != curation_list.columns:
                raise ValueError(f"{path.name}: header {reader.fieldnames} != {list(curation_list.columns)}")
            for line, row in enumerate(reader, start=2):
                try:
                    results[upsert(list_name, row)] += 1
                except InvalidRow as e:
                    raise ValueError(f"{path.name}:{line}: {e.errors}") from e
    return results
