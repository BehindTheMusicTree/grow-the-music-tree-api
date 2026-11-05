import logging

from django.db import connection, transaction
from django.utils import timezone
from django_q.tasks import async_task

from grow.model.song_search.SongSearchState import SongSearchState
from grow.search.cache import SearchCache, invalidate_search_cache
from grow.song_search.projection import COLUMNS, PROJECTION, TABLE

NEW_TABLE = f"{TABLE}_new"
NEW_SUFFIX = "_new"
BUILD_GROUP = "song-search-build"

logger = logging.getLogger("grow.bulk_import")


def rebuild_song_search(*, only_if_not_ready: bool = False) -> int | None:
    """
    Fills a fresh copy of the projection from the source tables and swaps it in, then marks search ready. Returns the
    row count, or None when `only_if_not_ready` is set and the projection was already built (the lock serializes
    concurrent builds, so duplicate queued builds are no-ops). Searches keep reading the old table until the swap; merges and ORM writes wait for it, then land in the
    new table, so no change made during the rebuild is lost.
    """
    if connection.vendor != "postgresql":
        raise RuntimeError("The song search projection is Postgres-only")
    with transaction.atomic(), connection.cursor() as cursor:
        # EXCLUSIVE still admits searches (ACCESS SHARE) but blocks every writer until the swap commits.
        cursor.execute(f"LOCK TABLE {TABLE} IN EXCLUSIVE MODE")
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'p'",
            [TABLE],
        )
        if only_if_not_ready and SongSearchState.load().ready:
            return None
        (primary_key,) = cursor.fetchone()
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = %s"
            " AND indexname <> %s ORDER BY indexname",
            [TABLE, primary_key],
        )
        indexes = cursor.fetchall()

        cursor.execute(f"DROP TABLE IF EXISTS {NEW_TABLE}")
        cursor.execute(f"CREATE TABLE {NEW_TABLE} (LIKE {TABLE} INCLUDING DEFAULTS)")
        cursor.execute(f"INSERT INTO {NEW_TABLE} ({COLUMNS}) {PROJECTION} ORDER BY s.track_id")
        rows = cursor.rowcount
        # Indexes are built after the fill, which is much faster than maintaining them row by row.
        cursor.execute(f"ALTER TABLE {NEW_TABLE} ADD CONSTRAINT {primary_key}{NEW_SUFFIX} PRIMARY KEY (track_id)")
        for name, definition in indexes:
            cursor.execute(_retarget(definition, name))

        cursor.execute(f"DROP TABLE {TABLE}")
        cursor.execute(f"ALTER TABLE {NEW_TABLE} RENAME TO {TABLE}")
        cursor.execute(f"ALTER TABLE {TABLE} RENAME CONSTRAINT {primary_key}{NEW_SUFFIX} TO {primary_key}")
        for name, _ in indexes:
            cursor.execute(f"ALTER INDEX {name}{NEW_SUFFIX} RENAME TO {name}")

        SongSearchState.objects.update_or_create(pk=1, defaults={"ready": True, "rebuilt_on": timezone.now()})
        transaction.on_commit(lambda: invalidate_search_cache(SearchCache.SONGS))
    with connection.cursor() as cursor:
        cursor.execute(f"ANALYZE {TABLE}")
    return rows


def _retarget(definition: str, name: str) -> str:
    """Points a `pg_indexes.indexdef` (`CREATE INDEX <name> ON <schema>.<table> USING ...`) at the new table, under a
    temporary name."""
    prefix = f"INDEX {name} ON "
    start = definition.find(prefix)
    using = definition.find(" USING ", start)
    if start < 0 or using < 0 or definition[start + len(prefix) : using].rsplit(".", 1)[-1] != TABLE:
        raise RuntimeError(f"Unexpected index definition: {definition}")
    return f"{definition[:start]}INDEX {name}{NEW_SUFFIX} ON {NEW_TABLE}{definition[using:]}"


def queue_song_search_build() -> None:
    """Queues the bulk build in its own task, so it gets a full task timeout apart from the merge that asked for it."""
    if connection.vendor != "postgresql":
        return
    logger.info("Song search projection not built: queueing its bulk build")
    async_task(rebuild_song_search, only_if_not_ready=True, group=BUILD_GROUP)
