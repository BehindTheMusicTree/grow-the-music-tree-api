import json

import pytest
from rest_framework.exceptions import ValidationError

from grow.artist.bulk_import.part_loader import _row
from tests.integration.artist.test_artist_import_runs import ARTIST, BAND, IMAGE

RELEASE_GROUP = ARTIST["release_groups"][0]


def _line(**overrides) -> bytes:
    return json.dumps({**ARTIST, **overrides}).encode()


def test_valid_artist_then_mbid_and_data():
    assert _row(1, _line()) == (BAND, json.dumps(ARTIST))


@pytest.mark.parametrize(
    "image",
    [
        IMAGE,
        None,
        {**IMAGE, "author": None},
        {**IMAGE, "license_url": None},
        {**IMAGE, "license_url": "http://creativecommons.org/licenses/by-sa/3.0"},
    ],
    ids=["full", "null", "no-author", "no-license-url", "http-license-url"],
)
def test_valid_image_then_accepted(image):
    artist = {**ARTIST, "image": image}

    assert _row(1, json.dumps(artist).encode()) == (BAND, json.dumps(artist))


@pytest.mark.parametrize(
    "line",
    [
        b"{not json",
        b"[]",
        _line(musicbrainz_artist_id=None),
        _line(name=""),
        _line(type="band"),
        _line(country="GBR"),
        _line(begin_year="1965"),
        _line(end_year=True),
        _line(ended=None),
        _line(members={}),
        _line(links=["https://pinkfloyd.com"]),
        _line(
            members=[
                {"musicbrainz_artist_id": "nope", "begin_year": None, "end_year": None, "ended": False, "roles": []}
            ]
        ),
        _line(
            members=[
                {"musicbrainz_artist_id": BAND, "begin_year": 99999, "end_year": None, "ended": False, "roles": []}
            ]
        ),
        _line(
            members=[
                {"musicbrainz_artist_id": BAND, "begin_year": None, "end_year": None, "ended": False, "roles": [""]}
            ]
        ),
        _line(members=[{"musicbrainz_artist_id": BAND, "begin_year": None, "end_year": None, "roles": []}]),
        _line(links=[{"kind": "myspace", "url": "https://myspace.com"}]),
        _line(links=[{"kind": "official", "url": ""}]),
        _line(links=[{"kind": "official", "url": "javascript:alert(1)"}]),
        _line(links=[{"kind": "official", "url": "ftp://x.org/"}]),
        _line(links=[{"kind": "official", "url": "www.pinkfloyd.com"}]),
        _line(links=[{"kind": "official", "url": "https://x.org/" + "a" * 2048}]),
        _line(links=[{"kind": "official", "url": "é" * 1100}]),
        _line(release_groups=[{**RELEASE_GROUP, "musicbrainz_release_group_id": None}]),
        _line(release_groups=[{**RELEASE_GROUP, "title": "x" * 2049}]),
        _line(release_groups=[{**RELEASE_GROUP, "primary_type": ""}]),
        _line(release_groups=[{**RELEASE_GROUP, "secondary_types": None}]),
        _line(release_groups=[{**RELEASE_GROUP, "first_release_year": -1}]),
        _line(release_groups=[{**RELEASE_GROUP, "first_release_year": 999}]),
        _line(image=IMAGE["url"]),
        _line(image={**IMAGE, "url": "http://upload.wikimedia.org/x.jpg"}),
        _line(image={**IMAGE, "page_url": None}),
        _line(image={**IMAGE, "license": ""}),
        _line(image={**IMAGE, "license": None}),
        _line(image={**IMAGE, "author": ""}),
        _line(image={**IMAGE, "url": "https://x.org/" + "a" * 2048}),
        _line(image={**IMAGE, "license_url": "https://x.org/" + "a" * 2048}),
        _line(image={**IMAGE, "license_url": "javascript:alert(1)"}),
    ],
)
def test_invalid_artist_then_validation_error(line):
    with pytest.raises(ValidationError):
        _row(1, line)
