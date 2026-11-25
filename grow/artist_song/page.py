"""
One keyset page of an artist's songs, read from `grow_artist_song`. Each ordering is a single index range scan whatever
the artist's size or the page's depth, because the sort keys live in the table and its two indexes carry the order:
`title` -> (artist_id, title, song_id), `-albumYear` -> (artist_id, album_year DESC NULLS LAST, song_id DESC).
"""

import uuid

from django.db import connection
from django.db.models import F, QuerySet

from grow.model.artist_song.ArtistSong import ArtistSong
from grow.view.pagination.song_cursor import ARTIST_DEFAULT_ORDERING, SongCursor

TITLE = "title"
ALBUM_YEAR_DESC = "-albumYear"
ORDERINGS = (TITLE, ALBUM_YEAR_DESC)
DEFAULT_ORDERING = ARTIST_DEFAULT_ORDERING
_TABLE = ArtistSong._meta.db_table


def _song_id_param(song_id: uuid.UUID) -> object:
    """Raw SQL bypasses the ORM's UUID adaptation: SQLite stores UUIDs as hex text."""
    return ArtistSong._meta.get_field("song").get_db_prep_value(song_id, connection)


def _title_rows(rows: QuerySet, cursor: SongCursor | None, inclusive: bool) -> QuerySet:
    if cursor is None:
        return rows
    after = ">=" if inclusive else ">"
    return rows.extra(
        where=[f"({_TABLE}.title, {_TABLE}.song_id) {after} (%s, %s)"],
        params=[cursor.key, _song_id_param(cursor.song_id)],
    )


def _dated_rows(rows: QuerySet, cursor: SongCursor | None, inclusive: bool) -> QuerySet:
    """The dated part of `-albumYear` from `cursor` on; empty once the cursor is in the undated tail."""
    if cursor and cursor.key is None:
        return rows.none()
    dated = rows.filter(album_year__isnull=False)
    if cursor is None:
        return dated
    after = "<=" if inclusive else "<"
    return dated.extra(
        where=[f"({_TABLE}.album_year, {_TABLE}.song_id) {after} (%s, %s)"],
        params=[cursor.key, _song_id_param(cursor.song_id)],
    )


def _undated_rows(rows: QuerySet, cursor: SongCursor | None, inclusive: bool) -> QuerySet:
    undated = rows.filter(album_year__isnull=True)
    if cursor and cursor.key is None:
        return undated.filter(**{"song_id__lte" if inclusive else "song_id__lt": cursor.song_id})
    return undated


def anchor(artist_id: uuid.UUID, ordering: str, song_id: uuid.UUID) -> SongCursor | None:
    """The cursor of `song_id`'s own row, or None if the artist isn't credited on it."""
    column = TITLE if ordering == TITLE else "album_year"
    keys = list(ArtistSong.objects.filter(artist_id=artist_id, song_id=song_id).values_list(column, flat=True)[:1])
    return SongCursor(ordering, keys[0], song_id) if keys else None


def count(artist_id: uuid.UUID, ordering: str, start: SongCursor | None) -> int:
    """The artist's songs, from `start` (included) on."""
    rows = ArtistSong.objects.filter(artist_id=artist_id)
    if start is None:
        return rows.count()
    if ordering == TITLE:
        return _title_rows(rows, start, True).count()
    return _dated_rows(rows, start, True).count() + _undated_rows(rows, start, True).count()


def page(
    artist_id: uuid.UUID, ordering: str, cursor: SongCursor | None, size: int, *, inclusive: bool = False
) -> list[tuple[uuid.UUID, SongCursor]]:
    """Up to `size` rows after (or from, if `inclusive`) `cursor`, as (song id, cursor of that row), in `ordering`."""
    rows = ArtistSong.objects.filter(artist_id=artist_id)
    if ordering == TITLE:
        found = _title_rows(rows, cursor, inclusive).order_by(TITLE, "song_id").values_list("song_id", TITLE)[:size]
        return [(song_id, SongCursor(ordering, title, song_id)) for song_id, title in found]
    # Descending year, years-less songs last, song id descending inside a year: a row comparison can't express the NULLS
    # LAST boundary, so the dated rows and the undated tail are two ordered scans, the second only if the first runs short.
    # The dated scan spells out NULLS LAST: a bare DESC means NULLS FIRST on Postgres, which the index doesn't carry, so
    # the planner would read all the artist's dated rows and sort them instead of walking the index.
    dated = _dated_rows(rows, cursor, inclusive).order_by(F("album_year").desc(nulls_last=True), "-song_id")
    found: list[tuple[uuid.UUID, SongCursor]] = [
        (song_id, SongCursor(ordering, year, song_id))
        for song_id, year in dated.values_list("song_id", "album_year")[:size]
    ]
    if len(found) < size:
        undated = _undated_rows(rows, cursor, inclusive).order_by("-song_id")
        found += [
            (song_id, SongCursor(ordering, None, song_id))
            for song_id in undated.values_list("song_id", flat=True)[: size - len(found)]
        ]
    return found
