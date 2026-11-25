import base64
import json
from uuid import uuid4

import pytest
from rest_framework.exceptions import ParseError

from grow.view.pagination.song_cursor import PK_ORDERING, SongCursor

SONG_ID = uuid4()


def _raw(payload) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


@pytest.mark.parametrize(
    ("ordering", "key"),
    [(PK_ORDERING, None), ("title", "a"), ("-title", ""), ("albumYear", 1999), ("-albumYear", None)],
)
def test_round_trip(ordering, key):
    cursor = SongCursor(ordering, key, SONG_ID)

    assert SongCursor.decode(cursor.encode(), ordering) == cursor


@pytest.mark.parametrize(
    ("payload", "ordering"),
    [
        ([2, "title", "a", str(SONG_ID)], "title"),
        ([1, "title", 5, str(SONG_ID)], "title"),
        ([1, "title", "\x00", str(SONG_ID)], "title"),
        ([1, "albumYear", True, str(SONG_ID)], "albumYear"),
        ([1, "", "a", str(SONG_ID)], PK_ORDERING),
        ([1, "title", "a", 5], "title"),
        ([None, str(SONG_ID)], PK_ORDERING),
        ({"a": 1}, "title"),
    ],
)
def test_forged_cursors_are_rejected(payload, ordering):
    with pytest.raises(ParseError, match="Invalid cursor"):
        SongCursor.decode(_raw(payload), ordering)


def test_ordering_mismatch_is_rejected():
    with pytest.raises(ParseError, match="does not match"):
        SongCursor.decode(SongCursor("title", "a", SONG_ID).encode(), "-albumYear")


def test_legacy_genre_and_artist_cursors_are_decoded():
    genre_cursor = base64.urlsafe_b64encode(str(SONG_ID).encode()).decode()

    assert SongCursor.decode(genre_cursor, PK_ORDERING) == SongCursor(PK_ORDERING, None, SONG_ID)
    assert SongCursor.decode(_raw(["a", str(SONG_ID)]), "title") == SongCursor("title", "a", SONG_ID)
    with pytest.raises(ParseError):
        SongCursor.decode(genre_cursor, "title")
