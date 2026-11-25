"""Writes `curation_export.schema.json` from the curation list specs.

Describes the `GET /v1/curation/export/` response: CSV-ready rows, so every field is a string,
booleans being "true" or "" and a blank optional field "". Every column is present in every row.
"""

import json
from typing import Any

from the_music_tree_grow_contracts import SCHEMAS_DIR
from the_music_tree_grow_contracts.curation_lists import (
    COLUMN_CHOICES,
    CURATION_LISTS,
    EDGE_COLUMNS,
    ENTITY_ID_PATTERN,
    GENRE_ALIAS_LIST,
    GRAPH_ITEM_ID_PATTERN,
    GRAPH_LISTS,
    ITEM_ID_PATTERN,
    QID_ENTITY_LISTS,
)

SCHEMA_PATH = SCHEMAS_DIR / "curation_export.schema.json"
SCHEMA_ID = (
    "https://raw.githubusercontent.com/BehindTheMusicTree/grow-the-music-tree-api/main/"
    "packages/grow-contracts/src/the_music_tree_grow_contracts/schemas/curation_export.schema.json"
)
QID_PATTERN = r"Q[0-9]+"
INT_PATTERN = r"\s*(?:-?[1-9][0-9]*|0)\s*"
EDGE_RELATIONS = ("canonical_parent", "regional_genre_parent", "regional_overview", "secondary_parent")


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def _rows(row: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": row}


def _non_empty() -> dict[str, Any]:
    return {"type": "string", "minLength": 1}


def _column_pattern(list_name: str, column: str, kind: str) -> str | None:
    if kind == "item_id":
        graph_id = list_name in GRAPH_LISTS or (list_name == GENRE_ALIAS_LIST and column == "target_item_id")
        return GRAPH_ITEM_ID_PATTERN if graph_id else ITEM_ID_PATTERN
    if kind == "tradition_id":
        return QID_PATTERN
    if kind == "entity_id":
        return QID_PATTERN if list_name in QID_ENTITY_LISTS else ENTITY_ID_PATTERN
    return INT_PATTERN if kind == "int" else None


def _column_schema(list_name: str, column: str, kind: str, optional: bool) -> dict[str, Any]:
    if kind == "bool":
        return {"type": "string", "enum": ["true", ""]}
    choices = COLUMN_CHOICES.get(list_name, {}).get(column)
    if choices:
        return {"type": "string", "enum": [*choices, ""] if optional else list(choices)}
    pattern = _column_pattern(list_name, column, kind)
    if pattern is None:
        return {"type": "string"} if optional else _non_empty()
    return {"type": "string", "pattern": f"^(?:{pattern}){'?' if optional else ''}$"}


def _list_schema(list_name: str) -> dict[str, Any]:
    specs = CURATION_LISTS[list_name].column_specs(list_name)
    return _rows(_object({s["name"]: _column_schema(list_name, s["name"], s["kind"], s["optional"]) for s in specs}))


def _edge_schema() -> dict[str, Any]:
    columns = {
        "relation": {"type": "string", "enum": list(EDGE_RELATIONS)},
        "item_id": _non_empty(),
        "parent_item_id": _non_empty(),
        "action": {"type": "string", "enum": ["add", "remove", ""]},
        "exclude_other_parents": {"type": "string", "enum": ["true", ""]},
        "reason": {"type": "string"},
    }
    return _object({column: columns[column] for column in EDGE_COLUMNS})


def build_curation_export_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {name: _list_schema(name) for name in CURATION_LISTS}
    properties["edges"] = _rows(_edge_schema())
    properties["exported_on"] = {"type": "string", "format": "date-time"}
    required = list(properties)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "Curation export",
        **_object(properties, required),
    }


def render() -> str:
    return json.dumps(build_curation_export_schema(), indent=2) + "\n"


if __name__ == "__main__":
    SCHEMA_PATH.write_text(render(), encoding="utf-8")
