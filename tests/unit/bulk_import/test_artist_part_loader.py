import json

import pytest
from rest_framework.exceptions import ValidationError

from grow.artist.bulk_import.part_loader import _row
from tests.integration.artist.test_artist_import_runs import ARTIST, BAND

RELEASE_GROUP = ARTIST["release_groups"][0]


def _line(**overrides) -> bytes:
    return json.dumps({**ARTIST, **overrides}).encode()


def test_valid_artist_then_mbid_and_data():
    assert _row(1, _line()) == (BAND, json.dumps(ARTIST))


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
        _line(release_groups=[{**RELEASE_GROUP, "musicbrainz_release_group_id": None}]),
        _line(release_groups=[{**RELEASE_GROUP, "title": "x" * 2049}]),
        _line(release_groups=[{**RELEASE_GROUP, "primary_type": ""}]),
        _line(release_groups=[{**RELEASE_GROUP, "secondary_types": None}]),
        _line(release_groups=[{**RELEASE_GROUP, "first_release_year": -1}]),
        _line(release_groups=[{**RELEASE_GROUP, "first_release_year": 999}]),
    ],
)
def test_invalid_artist_then_validation_error(line):
    with pytest.raises(ValidationError):
        _row(1, line)
