from typing import Any

from django.urls import reverse

from grow.openapi.documents import component_ref, object_schema
from grow.region_map.bulk_import.merge import SCHEMA_NAMES

_STRING = {"type": "string"}
_HEADER = {"schema": _STRING}
_ETAG = {"ETag": {"schema": _STRING, "required": True}}
_IF_NONE_MATCH = {"name": "If-None-Match", "in": "header", **_HEADER}


def legacy_region_map() -> dict[str, Any]:
    # Old indexes were checked before storage, then served byte for byte even after the format changed.
    genre = object_schema({"itemId": _STRING}, closed=False)
    region = object_schema({"genres": {"type": "array", "items": genre}}, closed=False)
    hidden_region = object_schema({"id": _STRING}, closed=False)
    return {
        "type": "object",
        "description": "Index archived before the current region map contract. Hidden regions may be inline.",
        "required": ["tileset", "regions"],
        "not": {"required": ["files"]},
        "properties": {
            "tileset": {"type": "string", "pattern": "^[0-9a-f]{64}$", "maxLength": 64},
            "regions": {"type": "array", "items": region},
            "hiddenRegions": {"type": "array", "items": hidden_region},
        },
    }


def _json_response(schema: dict[str, Any], description: str, **kwargs: Any) -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"schema": schema}}, **kwargs}


def region_map_paths() -> dict[str, Any]:
    missing = _json_response(object_schema({"detail": _STRING}), "No region map snapshot or file is available.")
    lexicon_row = object_schema(
        {
            "wikidataId": _STRING,
            "uuid": {"type": "string", "format": "uuid"},
            "name": _STRING,
            "treeName": _STRING,
            "genrePlaylistUuid": {"type": ["string", "null"], "format": "uuid"},
            "isUmbrella": {"type": "boolean"},
            "viewsCount": {"type": "integer"},
        }
    )
    attachable_row = object_schema(
        {
            "id": _STRING,
            "name": _STRING,
            "kind": _STRING,
            "hidden": {"type": "boolean"},
        }
    )
    # The ordinary Django views do not appear in DRF's endpoint enumeration.
    return {
        reverse("region-map-index"): {
            "get": {
                "operationId": "region_map_index",
                "tags": ["regions"],
                "security": [],
                "parameters": [_IF_NONE_MATCH, {"name": "Accept-Encoding", "in": "header", **_HEADER}],
                "responses": {
                    "200": _json_response(
                        {"anyOf": [component_ref("RegionMap"), component_ref("LegacyRegionMap")]},
                        "Latest region map. The ETag is specific to the encoding.",
                        headers={**_ETAG, "Content-Encoding": {"schema": {"const": "gzip"}}},
                    ),
                    "304": {"description": "The matching representation is unchanged.", "headers": _ETAG},
                    "404": missing,
                },
            }
        },
        reverse("region-map-genres"): {
            "get": {
                "operationId": "region_map_genres",
                "tags": ["regions"],
                "security": [],
                "parameters": [_IF_NONE_MATCH],
                "responses": {
                    "200": _json_response(
                        {"type": "array", "items": lexicon_row}, "Genres referenced by the latest map.", headers=_ETAG
                    ),
                    "304": {"description": "The genre lexicon is unchanged.", "headers": _ETAG},
                    "404": missing,
                },
            }
        },
        reverse("region-map-attachable"): {
            "get": {
                "operationId": "region_map_attachable",
                "tags": ["regions"],
                "security": [],
                "responses": {
                    "200": _json_response(
                        {"type": "array", "items": attachable_row},
                        "Visible and hidden targets for tradition placement.",
                    ),
                    "404": missing,
                },
            }
        },
    }


def region_map_import_row(component_names: dict[str, str]) -> dict[str, Any]:
    return {
        "oneOf": [
            object_schema(
                {
                    "path": {"const": path},
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "document": component_ref(component_names[name]),
                },
                closed=False,
            )
            for path, name in SCHEMA_NAMES.items()
        ]
    }
