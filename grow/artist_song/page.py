"""
One keyset page of an artist's songs, read from `grow_artist_song`. Each ordering is a single index range scan whatever
the artist's size or the page's depth, because the sort keys live in the table and its two indexes carry the order:
`title` -> (artist_id, title, song_id), `-albumYear` -> (artist_id, album_year DESC NULLS LAST, song_id DESC).
"""

import base64
import binascii
import json
import uuid
from dataclasses import dataclass

from django.db import connection
from rest_framework.exceptions import ParseError

from grow.model.artist_song.ArtistSong import ArtistSong

TITLE = "title"
ALBUM_YEAR_DESC = "-albumYear"
ORDERINGS = (TITLE, ALBUM_YEAR_DESC)
DEFAULT_ORDERING = TITLE
_TABLE = ArtistSong._meta.db_table


def _song_id_param(song_id: uuid.UUID) -> object:
    """Raw SQL bypasses the ORM's UUID adaptation: SQLite stores UUIDs as hex text."""
    return ArtistSong._meta.get_field("song").get_db_prep_value(song_id, connection)


@dataclass(frozen=True)
class Cursor:
    """The last row of the previous page: its sort key (title, year, or None for a year-less song) and song id."""

    key: str | int | None
    song_id: uuid.UUID

    def encode(self) -> str:
        return base64.urlsafe_b64encode(json.dumps([self.key, str(self.song_id)]).encode()).decode()

    @classmethod
    def decode(cls, value: str, ordering: str) -> Cursor:
        try:
            key, song_id = json.loads(base64.urlsafe_b64decode(value.encode()))
            cursor = cls(key, uuid.UUID(song_id))
        except (ValueError, TypeError, AttributeError, binascii.Error, UnicodeDecodeError) as error:
            raise ParseError("Invalid cursor.") from error
        valid_key = isinstance(key, str) if ordering == TITLE else key is None or type(key) is int
        if not valid_key or (isinstance(key, str) and "\x00" in key):
            raise ParseError("Invalid cursor.")
        return cursor


def page(artist_id: uuid.UUID, ordering: str, cursor: Cursor | None, size: int) -> list[tuple[uuid.UUID, Cursor]]:
    """Up to `size` rows after `cursor`, as (song id, cursor of that row), in `ordering`."""
    rows = ArtistSong.objects.filter(artist_id=artist_id)
    if ordering == TITLE:
        if cursor:
            rows = rows.extra(
                where=[f"({_TABLE}.title, {_TABLE}.song_id) > (%s, %s)"],
                params=[cursor.key, _song_id_param(cursor.song_id)],
            )
        found = rows.order_by(TITLE, "song_id").values_list("song_id", TITLE)[:size]
        return [(song_id, Cursor(title, song_id)) for song_id, title in found]
    # Descending year, years-less songs last, song id descending inside a year: a row comparison can't express the NULLS
    # LAST boundary, so the dated rows and the undated tail are two ordered scans, the second only if the first runs short.
    found: list[tuple[uuid.UUID, Cursor]] = []
    if cursor is None or cursor.key is not None:
        dated = rows.filter(album_year__isnull=False)
        if cursor:
            dated = dated.extra(
                where=[f"({_TABLE}.album_year, {_TABLE}.song_id) < (%s, %s)"],
                params=[cursor.key, _song_id_param(cursor.song_id)],
            )
        found = [
            (song_id, Cursor(year, song_id))
            for song_id, year in dated.order_by("-album_year", "-song_id").values_list("song_id", "album_year")[:size]
        ]
    if len(found) < size:
        undated = rows.filter(album_year__isnull=True)
        if cursor and cursor.key is None:
            undated = undated.filter(song_id__lt=cursor.song_id)
        found += [
            (song_id, Cursor(None, song_id))
            for song_id in undated.order_by("-song_id").values_list("song_id", flat=True)[: size - len(found)]
        ]
    return found
