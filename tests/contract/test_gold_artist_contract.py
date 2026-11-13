"""Gold artist export: grow's JSON Schema and the hand-written per-row checks of the import must not drift.

The import validates millions of rows with `_row` (fast), so the schema is not run at import time; these tests keep the
two in step instead: a sample covering every schema property passes both, each constraint's violation fails both, and the
enums and length limits match the models and settings.
"""

import copy
import json

import pytest
from django.conf import settings
from jsonschema import Draft202012Validator
from rest_framework.exceptions import ValidationError

from grow.artist.bulk_import.part_loader import _row
from grow.model.artist.Artist import Artist
from grow.model.artist_link.ArtistLink import ArtistLink
from grow.schemas import load_gold_schema
from tests.utils.json_schema import keys_used, property_names

MBID = "0383dadf-2a4e-4d10-a46a-e9e041da8eb3"
OTHER_MBID = "5b11f4ce-a62d-471e-81fc-a69a8278c7da"
IMAGE = {
    "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/Example.jpg",
    "page_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
    "author": "Jane Doe",
    "license": "CC BY-SA 4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
}
SAMPLE = {
    "musicbrainz_artist_id": MBID,
    "name": "Contract Band",
    "type": "group",
    "country": "FR",
    "begin_year": 1990,
    "end_year": 2005,
    "ended": True,
    "disambiguation": "the contract one",
    "aliases": ["The Contracts"],
    "members": [
        {"musicbrainz_artist_id": OTHER_MBID, "begin_year": 1990, "end_year": None, "ended": False, "roles": ["vocals"]}
    ],
    "links": [{"kind": "official", "url": "https://example.com/band"}],
    "release_groups": [
        {
            "musicbrainz_release_group_id": OTHER_MBID,
            "title": "First Record",
            "primary_type": "Album",
            "secondary_types": ["Live"],
            "first_release_year": 1995,
        }
    ],
    "image": IMAGE,
    "origin": {
        "name": "Paris",
        "musicbrainz_area_id": OTHER_MBID,
        "kind": "City",
        "source": "begin_area",
        "wikidata_id": "Q90",
        "longitude": 2.35,
        "latitude": 48.85,
        "region_id": "FR",
    },
}


def _accepted_by_row(artist: dict) -> bool:
    try:
        _row(1, json.dumps(artist).encode())
    except ValidationError:
        return False
    return True


def _valid_for_schema(artist: dict) -> bool:
    return Draft202012Validator(load_gold_schema("artist")).is_valid(artist)


def _mutated(path: tuple, value) -> dict:
    artist = copy.deepcopy(SAMPLE)
    target = artist
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return artist


VIOLATIONS = {
    "bad mbid": _mutated(("musicbrainz_artist_id",), "not-a-uuid"),
    "empty name": _mutated(("name",), ""),
    "name too long": _mutated(("name",), "x" * (settings.ARTIST_NAME_LEN_MAX + 1)),
    "unknown type": _mutated(("type",), "robot"),
    "country lowercase": _mutated(("country",), "fr"),
    "country length": _mutated(("country",), "FRA"),
    "year too high": _mutated(("begin_year",), 32768),
    "year too low": _mutated(("end_year",), -32769),
    "ended not boolean": _mutated(("ended",), "yes"),
    "empty disambiguation": _mutated(("disambiguation",), ""),
    "disambiguation too long": _mutated(("disambiguation",), "x" * (settings.ARTIST_NAME_LEN_MAX + 1)),
    "empty alias": _mutated(("aliases",), [""]),
    "member bad mbid": _mutated(("members", 0, "musicbrainz_artist_id"), "nope"),
    "member roles not strings": _mutated(("members", 0, "roles"), [1]),
    "unknown link kind": _mutated(("links", 0, "kind"), "myspace"),
    "link not http": _mutated(("links", 0, "url"), "ftp://example.com"),
    "release group bad mbid": _mutated(("release_groups", 0, "musicbrainz_release_group_id"), "nope"),
    "release group empty title": _mutated(("release_groups", 0, "title"), ""),
    "release group title too long": _mutated(("release_groups", 0, "title"), "x" * (settings.ALBUM_NAME_LEN_MAX + 1)),
    "release year not four digits": _mutated(("release_groups", 0, "first_release_year"), 999),
    "image not https": _mutated(("image", "url"), "http://example.com/a.jpg"),
    "origin unknown source": _mutated(("origin", "source"), "birthplace"),
    "origin bad qid": _mutated(("origin", "wikidata_id"), "Q0"),
    "origin longitude out of range": _mutated(("origin", "longitude"), 181),
    "origin latitude out of range": _mutated(("origin", "latitude"), -91),
    "origin region id too long": _mutated(("origin", "region_id"), "x" * 65),
}


def test_sample_is_accepted_by_schema_and_import():
    assert _valid_for_schema(SAMPLE)
    assert _accepted_by_row(SAMPLE)


def test_sample_covers_every_schema_property():
    declared, used = property_names(load_gold_schema("artist")), keys_used(SAMPLE)

    assert declared == used, {"unused": declared - used, "unknown": used - declared}


@pytest.mark.parametrize("name", VIOLATIONS)
def test_violation_is_rejected_by_schema_and_import(name):
    assert not _valid_for_schema(VIOLATIONS[name])
    assert not _accepted_by_row(VIOLATIONS[name])


# The import tolerates the other required keys missing (parts exported before they existed): it only states what it needs.
REQUIRED_BY_IMPORT = ("musicbrainz_artist_id", "name", "ended", "members", "links", "release_groups")


@pytest.mark.parametrize("key", REQUIRED_BY_IMPORT)
def test_key_required_by_the_import_is_required_by_the_schema(key):
    artist = {k: v for k, v in SAMPLE.items() if k != key}

    assert key in load_gold_schema("artist")["required"]
    assert not _valid_for_schema(artist)
    assert not _accepted_by_row(artist)


def test_enums_match_the_models():
    schema = load_gold_schema("artist")
    properties = schema["properties"]
    link_kinds = set(properties["links"]["items"]["properties"]["kind"]["enum"])
    origin_sources = set(properties["origin"]["properties"]["source"]["enum"])

    assert set(properties["type"]["enum"]) - {None} == set(Artist.Type.values)
    assert link_kinds == set(ArtistLink.Kind.values)
    assert origin_sources == set(Artist.OriginSource.values)


def test_length_limits_match_settings():
    properties = load_gold_schema("artist")["properties"]
    release_group = properties["release_groups"]["items"]["properties"]

    assert properties["name"]["maxLength"] == settings.ARTIST_NAME_LEN_MAX
    assert properties["disambiguation"]["maxLength"] == settings.ARTIST_NAME_LEN_MAX
    assert release_group["title"]["maxLength"] == settings.ALBUM_NAME_LEN_MAX
