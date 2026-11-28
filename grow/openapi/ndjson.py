from copy import deepcopy
from typing import Any

from the_music_tree_grow_contracts.curation_lists import ITEM_ID_PATTERN

from grow.openapi.documents import component_ref, object_schema
from grow.serializer.schema.genre_graph import ASSIGNMENTS_SCHEMA
from grow.track.bulk_import.part_loader import MAX_LENGTHS, MAX_RECORDING_COUNT, MAX_VIEW_COUNT, REASONS, TEXT_COLUMNS

UUID = {"type": "string", "format": "uuid"}
ASSIGNMENT_ROW = object_schema({"musicbrainz_recording_id": UUID, "assignments": ASSIGNMENTS_SCHEMA})


def _nullable_integer(minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": ["integer", "null"], "minimum": minimum, "maximum": maximum}


def song_row() -> dict[str, Any]:
    properties: dict[str, Any] = {column: {"type": ["string", "null"], "minLength": 1} for column in TEXT_COLUMNS}
    for column, limit in MAX_LENGTHS.items():
        properties[column]["maxLength"] = limit
    for column in ("title", "artist"):
        properties[column]["type"] = "string"
    properties.update(
        musicbrainz_recording_id=UUID,
        artist_musicbrainz_id={**UUID, "type": ["string", "null"]},
        youtube_unplayable_reason={"enum": [*sorted(REASONS), None]},
        genre_wikidata_id={"type": ["string", "null"], "pattern": ITEM_ID_PATTERN},
        youtube_view_count=_nullable_integer(0, MAX_VIEW_COUNT),
        first_release_year=_nullable_integer(0, 32767),
        recording_count=_nullable_integer(1, MAX_RECORDING_COUNT),
        youtube_region_restriction={
            "anyOf": [
                {"type": "null"},
                {
                    **object_schema(
                        {
                            "mode": {"enum": ["allowed", "blocked", "unrestricted"]},
                            "countries": {
                                "type": "array",
                                "items": {"type": "string", "pattern": "^(?!XX$)[A-Z]{2}$", "maxLength": 2},
                            },
                        }
                    ),
                    "if": {"properties": {"mode": {"const": "unrestricted"}}},
                    "then": {"properties": {"countries": {"maxItems": 0}}},
                },
            ]
        },
    )
    return {
        "type": "object",
        "properties": properties,
        "required": ["musicbrainz_recording_id", "title", "artist", "first_release_year"],
        "if": {
            "required": ["youtube_region_restriction"],
            "properties": {"youtube_region_restriction": {"type": "object"}},
        },
        "then": {"required": ["youtube_video_id"], "properties": {"youtube_video_id": {"type": "string"}}},
    }


def artist_upload_row(producer_row: dict[str, Any]) -> dict[str, Any]:
    # The loader defaults missing values in older artist parts and tolerates additional keys.
    row = deepcopy(producer_row)
    row["title"] = "Artist upload row"
    row["description"] = "An artist NDJSON line. Older exports may omit optional fields."
    row["required"] = ["musicbrainz_artist_id", "name", "ended", "members", "links", "release_groups"]
    row.pop("additionalProperties")
    properties = row["properties"]
    for key, optional in (
        ("members", ("begin_year", "end_year")),
        ("links", ()),
        ("release_groups", ("primary_type", "first_release_year")),
    ):
        item = properties[key]["items"]
        item["required"] = [field for field in item["required"] if field not in optional]
        item.pop("additionalProperties")
    properties["origin"]["required"] = ["name", "source"]
    properties["origin"].pop("additionalProperties")
    properties["origin"]["properties"]["musicbrainz_area_id"] = {}
    image = properties["image"]["oneOf"][1]
    image["required"] = ["url", "page_url", "license"]
    image.pop("additionalProperties")
    return row


def part_row(kind: str) -> dict[str, Any]:
    match kind:
        case "artists":
            return component_ref("ArtistUploadRow")
        case "region_map":
            return component_ref("RegionMapImportRow")
        case "songs":
            return song_row()
        case _:
            raise ValueError(f"No NDJSON row schema for {kind}")
