from __future__ import annotations

import uuid
from collections.abc import Iterable
from enum import StrEnum
from typing import TYPE_CHECKING

from django.db import connection, models, transaction
from rest_framework.exceptions import APIException

from grow.search.cache import SearchCache, invalidate_search_cache
from grow.song_search.projection import DRIFT, QUERY_TOKENS_MAX, TABLE, delete, upsert, words
from grow.youtube_regions import attemptable_sql

if TYPE_CHECKING:
    from grow.model.song.Song import Song
    from grow.model.song_search.SongSearch import SongSearch

STATEMENT_TIMEOUT = "3s"


class GenreFilter(StrEnum):
    ANY = "any"
    WITH = "with"
    WITHOUT = "without"


class SongSearchUnavailable(APIException):
    """The projection hasn't been built yet: `rebuild_song_search` never ran."""

    status_code = 503
    default_detail = "Song search is not available yet"
    default_code = "search_unavailable"


class SongSearchManager(models.Manager["SongSearch"]):
    def search(
        self,
        query: str,
        limit: int,
        genre: GenreFilter = GenreFilter.ANY,
        playable: bool | None = None,
        country: str | None = None,
    ) -> list[Song]:
        """
        Songs whose title and artist names hold every query word as a prefix, in any order. An exact title match
        comes first, then a title starting with the query, then the static `rank_score`. Postgres-only.
        """
        from grow.model.song.Song import Song

        with transaction.atomic(), connection.cursor() as cursor:
            # The timeout turns a pathological query into the 503 `query_timeout` instead of a stuck worker.
            cursor.execute(
                f"""SELECT set_config('statement_timeout', %s, true),
                    coalesce((SELECT ready FROM grow_song_search_state WHERE id = 1), false), {words("%s")}""",
                [STATEMENT_TIMEOUT, query],
            )
            _, ready, folded = cursor.fetchone()
            if not ready:
                raise SongSearchUnavailable
            tokens = folded.split()[:QUERY_TOKENS_MAX]
            if not tokens:
                return []
            filters, params = self._filters(genre, playable, country)
            cursor.execute(
                f"""WITH exact AS (
                    SELECT track_id, rank_score, 2 AS tier FROM {TABLE}
                    WHERE title_key COLLATE "C" = %(folded)s{filters}
                    ORDER BY rank_score DESC, track_id LIMIT %(limit)s
                ), prefix AS (
                    SELECT track_id, rank_score, 1 AS tier FROM {TABLE}
                    WHERE title_key COLLATE "C" LIKE %(prefix)s{filters}
                    ORDER BY rank_score DESC, track_id LIMIT %(limit)s
                ), tokens AS (
                    SELECT track_id, rank_score, 0 AS tier FROM {TABLE}
                    WHERE document @@ to_tsquery('simple', %(tsquery)s){filters}
                    ORDER BY rank_score DESC, track_id LIMIT %(limit)s
                )
                SELECT track_id FROM (
                    SELECT * FROM exact UNION ALL SELECT * FROM prefix UNION ALL SELECT * FROM tokens
                ) found
                GROUP BY track_id ORDER BY max(tier) DESC, max(rank_score) DESC, track_id LIMIT %(limit)s""",
                {
                    **params,
                    "folded": folded,
                    # `words` leaves only letters, digits and spaces, so no LIKE wildcard needs escaping.
                    "prefix": folded + "%",
                    "tsquery": " & ".join(f"'{token}':*" for token in tokens),
                    "limit": limit,
                },
            )
            track_ids = [row[0] for row in cursor.fetchall()]
            songs = Song.objects.select_related("genre").prefetch_related("artists").in_bulk(track_ids)
        return [songs[track_id] for track_id in track_ids if track_id in songs]

    @staticmethod
    def _filters(genre: GenreFilter, playable: bool | None, country: str | None = None) -> tuple[str, dict]:
        filters, params = "", {}
        if genre == GenreFilter.WITH:
            filters += " AND has_genre"
        elif genre == GenreFilter.WITHOUT:
            filters += " AND NOT has_genre"
        if playable is not None:
            predicate, region_params = attemptable_sql(country)
            filters += f" AND EXISTS (SELECT 1 FROM grow_song s WHERE s.track_id = {TABLE}.track_id AND ({predicate}) = %(playable)s)"
            params.update(region_params)
            params["playable"] = playable
        return filters, params

    def refresh(self, track_ids: Iterable[uuid.UUID]) -> None:
        """Re-derives the given songs' rows after an ORM write; songs that no longer exist lose theirs."""
        ids = list(track_ids)
        if not ids:
            return
        transaction.on_commit(lambda: invalidate_search_cache(SearchCache.SONGS))
        if connection.vendor != "postgresql":
            # The projection is Postgres-only (tsvector, unaccent); SQLite tests never search.
            return
        with connection.cursor() as cursor:
            cursor.execute(upsert("SELECT unnest(%(ids)s::uuid[])"), {"ids": ids})
            cursor.execute(
                delete(
                    "SELECT id FROM unnest(%(ids)s::uuid[]) id"
                    " WHERE NOT EXISTS (SELECT 1 FROM grow_song s WHERE s.track_id = id)"
                ),
                {"ids": ids},
            )

    def drift(self) -> dict[str, int]:
        """Rows missing from, orphaned in, or stale in the projection compared with the source tables."""
        with connection.cursor() as cursor:
            cursor.execute(DRIFT)
            missing, orphaned, stale = cursor.fetchone()
        return {"missing": missing, "orphaned": orphaned, "stale": stale}
