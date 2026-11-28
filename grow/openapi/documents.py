"""Embed the wire contracts as OpenAPI 3.1 components."""

import json
import re
from collections.abc import Callable, Iterator
from copy import deepcopy
from functools import partial
from importlib.resources import files
from typing import Any

from jsonschema import Draft7Validator
from the_music_tree_genre_graph import load_genre_graph_schema
from the_music_tree_grow_contracts import load_schema

DRAFT_7 = "http://json-schema.org/draft-07/schema#"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
GROW_DOCUMENTS = {
    "artist": "ArtistImportRow",
    "curation_export": "CurationExport",
    "genealogy": "Genealogy",
    "hidden_regions": "HiddenRegions",
    "region_map": "RegionMap",
    "synthesized_overview_alerts": "SynthesizedOverviewAlerts",
}


def load_genre_tree_schema() -> dict[str, Any]:
    return json.loads(files("the_music_tree_genre_kit").joinpath("schemas/genre_tree.schema.json").read_text())


DOCUMENTS: dict[str, Callable[[], dict[str, Any]]] = {
    **{component: partial(load_schema, name) for name, component in GROW_DOCUMENTS.items()},
    "GenreTree": load_genre_tree_schema,
    "GenreGraph": load_genre_graph_schema,
}


def component_ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def object_schema(properties: dict[str, Any], *, closed: bool = True) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "required": list(properties)}
    if closed:
        schema["additionalProperties"] = False
    return schema


def schema_children(schema: dict[str, Any]) -> Iterator[Any]:
    for key in ("properties", "patternProperties", "dependentSchemas"):
        yield from schema.get(key, {}).values()
    for key in ("allOf", "oneOf", "anyOf", "prefixItems"):
        yield from schema.get(key, [])
    for key in (
        "items",
        "additionalProperties",
        "not",
        "if",
        "then",
        "else",
        "contains",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
        "contentSchema",
    ):
        if key in schema:
            yield schema[key]


def adapt_document(name: str, source: dict[str, Any]) -> dict[str, Any]:
    root = deepcopy(source)
    dialect = root.pop("$schema")
    root.pop("$id", None)
    if dialect not in (DRAFT_7, DRAFT_2020_12):
        raise ValueError(f"{name}: unsupported schema dialect {dialect}")
    draft7 = dialect == DRAFT_7
    defs_key = "definitions" if draft7 else "$defs"
    definitions = root.pop(defs_key, {})
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", key) for key in definitions):
        raise ValueError(f"{name}: unsupported definition name")
    refs = {"#": name, **{f"#/{defs_key}/{key}": f"{name}_{key}" for key in definitions}}

    def adapt(schema: Any) -> None:
        if isinstance(schema, bool):
            return
        unsupported = schema.keys() & {
            "$id",
            "$schema",
            "$defs",
            "definitions",
            "$anchor",
            "$dynamicRef",
            "$dynamicAnchor",
            "$recursiveRef",
            "$recursiveAnchor",
            "dependencies",
        }
        if draft7:
            unsupported |= schema.keys() - (
                Draft7Validator.VALIDATORS.keys()
                | {
                    "title",
                    "description",
                    "default",
                    "examples",
                    "$comment",
                    "readOnly",
                    "writeOnly",
                    "contentEncoding",
                    "contentMediaType",
                    "additionalItems",
                    "then",
                    "else",
                }
            )
        if unsupported:
            raise ValueError(f"{name}: unsupported keywords {sorted(unsupported)}")
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref not in refs or (draft7 and len(schema) != 1):
                raise ValueError(f"{name}: unsupported reference {ref}")
            schema["$ref"] = component_ref(refs[ref])["$ref"]
        if draft7 and isinstance(schema.get("items"), list):
            schema["prefixItems"] = schema.pop("items")
            schema["items"] = schema.pop("additionalItems", True)
        if "additionalItems" in schema:
            raise ValueError(f"{name}: additionalItems without a tuple")
        for child in schema_children(schema):
            adapt(child)

    components = {name: root, **{f"{name}_{key}": value for key, value in definitions.items()}}
    for schema in components.values():
        adapt(schema)
    return components
