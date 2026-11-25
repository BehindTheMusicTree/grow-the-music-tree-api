"""
One keyset page of an artist's songs, read from `grow_artist_song`. Each ordering is a single index range scan whatever
the artist's size or the page's depth, because the sort keys live in the table and its two indexes carry the order:
`title` -> (artist_id, title, song_id), `-albumYear` -> (artist_id, album_year DESC NULLS LAST, song_id DESC).
"""

import uuid

from django.db import connection
from django.db.models import F

from grow.model.artist_song.ArtistSong import ArtistSong
from grow.view.pagination.song_cursor import SongCursor

TITLE = "title"
ALBUM_YEAR_DESC = "-albumYear"
ORDERINGS = (TITLE, ALBUM_YEAR_DESC)
DEFAULT_ORDERING = TITLE
_TABLE = ArtistSong._meta.db_table


def _song_id_param(song_id: uuid.UUID) -> object:
    """Raw SQL bypasses the ORM's UUID adaptation: SQLite stores UUIDs as hex text."""
    return ArtistSong._meta.get_field("song").get_db_prep_value(song_id, connection)


def page(
    artist_id: uuid.UUID, ordering: str, cursor: SongCursor | None, size: int
) -> list[tuple[uuid.UUID, SongCursor]]:
    """Up to `size` rows after `cursor`, as (song id, cursor of that row), in `ordering`."""
    rows = ArtistSong.objects.filter(artist_id=artist_id)
    if ordering == TITLE:
        if cursor:
            rows = rows.extra(
                where=[f"({_TABLE}.title, {_TABLE}.song_id) > (%s, %s)"],
                params=[cursor.key, _song_id_param(cursor.song_id)],
            )
        found = rows.order_by(TITLE, "song_id").values_list("song_id", TITLE)[:size]
        return [(song_id, SongCursor(ordering, title, song_id)) for song_id, title in found]
    # Descending year, years-less songs last, song id descending inside a year: a row comparison can't express the NULLS
    # LAST boundary, so the dated rows and the undated tail are two ordered scans, the second only if the first runs short.
    # The dated scan spells out NULLS LAST: a bare DESC means NULLS FIRST on Postgres, which the index doesn't carry, so
    # the planner would read all the artist's dated rows and sort them instead of walking the index.
    found: list[tuple[uuid.UUID, SongCursor]] = []
    if cursor is None or cursor.key is not None:
        dated = rows.filter(album_year__isnull=False)
        if cursor:
            dated = dated.extra(
                where=[f"({_TABLE}.album_year, {_TABLE}.song_id) < (%s, %s)"],
                params=[cursor.key, _song_id_param(cursor.song_id)],
            )
        found = [
            (song_id, SongCursor(ordering, year, song_id))
            for song_id, year in dated.order_by(F("album_year").desc(nulls_last=True), "-song_id").values_list(
                "song_id", "album_year"
            )[:size]
        ]
    if len(found) < size:
        undated = rows.filter(album_year__isnull=True)
        if cursor and cursor.key is None:
            undated = undated.filter(song_id__lt=cursor.song_id)
        found += [
            (song_id, SongCursor(ordering, None, song_id))
            for song_id in undated.order_by("-song_id").values_list("song_id", flat=True)[: size - len(found)]
        ]
    return found
