from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.db import connection, models
from rest_framework.exceptions import APIException

from grow.artist_song.projection import DRIFT, STATE_TABLE, delete_removed_links, delete_songs, upsert

if TYPE_CHECKING:
    from grow.model.artist_song.ArtistSong import ArtistSong


class ArtistSongUnavailable(APIException):
    """The projection hasn't been built yet: `rebuild_artist_song` never ran."""

    status_code = 503
    default_detail = "The artist song list is not available yet"
    default_code = "artist_songs_unavailable"


class ArtistSongManager(models.Manager["ArtistSong"]):
    def require_ready(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT coalesce((SELECT ready FROM {STATE_TABLE} WHERE id = 1), false)")
            if not cursor.fetchone()[0]:
                raise ArtistSongUnavailable

    def refresh_songs(self, song_ids: Iterable[uuid.UUID]) -> None:
        """Re-derives the given songs' rows after an ORM write; credits and songs that no longer exist lose theirs."""
        ids = list(song_ids)
        if not ids or connection.vendor != "postgresql":
            # The projection is Postgres-only (the song list never reads it elsewhere).
            return
        ids_sql = "SELECT unnest(%(ids)s::uuid[])"
        with connection.cursor() as cursor:
            cursor.execute(delete_removed_links(ids_sql), {"ids": ids})
            cursor.execute(upsert(ids_sql), {"ids": ids})

    def delete_songs(self, song_ids: Iterable[uuid.UUID]) -> None:
        ids = list(song_ids)
        if not ids or connection.vendor != "postgresql":
            return
        with connection.cursor() as cursor:
            cursor.execute(delete_songs("SELECT unnest(%(ids)s::uuid[])"), {"ids": ids})

    def drift(self) -> dict[str, int]:
        with connection.cursor() as cursor:
            cursor.execute(DRIFT)
            missing, orphaned, stale = cursor.fetchone()
        return {"missing": missing, "orphaned": orphaned, "stale": stale}
