import logging

from django.db import connection, transaction
from django.utils import timezone
from django_q.tasks import async_task

from grow.artist_song.projection import COLUMNS, FUNCTIONS, PROJECTION, TABLE
from grow.model.artist_song.ArtistSongState import ArtistSongState
from grow.projection.fingerprint import fingerprint
from grow.workload.admission import admitted

NEW_TABLE = f"{TABLE}_new"
NEW_SUFFIX = "_new"
BUILD_GROUP = "artist-song-build"

logger = logging.getLogger("grow.bulk_import")


@admitted
def rebuild_artist_song(*, only_if_not_ready: bool = False) -> int | None:
    """
    Fills a fresh copy of the projection from the source tables and swaps it in, then marks the artist song list ready.
    Returns the row count, or None when `only_if_not_ready` is set and the projection was already built. Reads keep
    using the old table until the swap; merges and ORM writes wait for it, then land in the new table.
    """
    if connection.vendor != "postgresql":
        raise RuntimeError("The artist song projection is Postgres-only")
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"LOCK TABLE {TABLE} IN EXCLUSIVE MODE")
        if only_if_not_ready and ArtistSongState.load().ready:
            return None
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'p'",
            [TABLE],
        )
        (primary_key,) = cursor.fetchone()
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = %s"
            " AND indexname <> %s ORDER BY indexname",
            [TABLE, primary_key],
        )
        indexes = cursor.fetchall()
        cursor.execute("SELECT reloptions FROM pg_class WHERE oid = %s::regclass", [TABLE])
        (reloptions,) = cursor.fetchone()

        cursor.execute(f"DROP TABLE IF EXISTS {NEW_TABLE}")
        cursor.execute(f"CREATE TABLE {NEW_TABLE} (LIKE {TABLE} INCLUDING DEFAULTS)")
        cursor.execute(f"INSERT INTO {NEW_TABLE} ({COLUMNS}) {PROJECTION} ORDER BY ta.artist_id, s.track_id")
        rows = cursor.rowcount
        # Indexes are built after the fill, which is much faster than maintaining them row by row.
        cursor.execute(
            f"ALTER TABLE {NEW_TABLE} ADD CONSTRAINT {primary_key}{NEW_SUFFIX} PRIMARY KEY (artist_id, song_id)"
        )
        for name, definition in indexes:
            cursor.execute(_retarget(definition, name))
        if reloptions:
            cursor.execute(f"ALTER TABLE {NEW_TABLE} SET ({', '.join(reloptions)})")

        cursor.execute(f"DROP TABLE {TABLE}")
        cursor.execute(f"ALTER TABLE {NEW_TABLE} RENAME TO {TABLE}")
        cursor.execute(f"ALTER TABLE {TABLE} RENAME CONSTRAINT {primary_key}{NEW_SUFFIX} TO {primary_key}")
        for name, _ in indexes:
            cursor.execute(f"ALTER INDEX {name}{NEW_SUFFIX} RENAME TO {name}")

        ArtistSongState.objects.update_or_create(
            pk=1,
            defaults={
                "ready": True,
                "rebuilt_on": timezone.now(),
                "fingerprint": current_fingerprint(cursor),
            },
        )
    with connection.cursor() as cursor:
        cursor.execute(f"ANALYZE {TABLE}")
    return rows


def current_fingerprint(cursor) -> str:
    return fingerprint(cursor, columns=COLUMNS, projection=PROJECTION, functions=FUNCTIONS)


def is_current() -> bool:
    """Whether the projection is built and its stored fingerprint matches the deployed definition."""
    state = ArtistSongState.load()
    with connection.cursor() as cursor:
        return state.ready and state.fingerprint == current_fingerprint(cursor)


def stamp_current() -> str:
    """Records the deployed definition's fingerprint, for a projection a clean drift check just proved equal to it."""
    with connection.cursor() as cursor:
        value = current_fingerprint(cursor)
    ArtistSongState.objects.update_or_create(pk=1, defaults={"fingerprint": value})
    return value


def _retarget(definition: str, name: str) -> str:
    """Points a `pg_indexes.indexdef` (`CREATE INDEX <name> ON <schema>.<table> USING ...`) at the new table, under a
    temporary name."""
    prefix = f"INDEX {name} ON "
    start = definition.find(prefix)
    using = definition.find(" USING ", start)
    if start < 0 or using < 0 or definition[start + len(prefix) : using].rsplit(".", 1)[-1] != TABLE:
        raise RuntimeError(f"Unexpected index definition: {definition}")
    return f"{definition[:start]}INDEX {name}{NEW_SUFFIX} ON {NEW_TABLE}{definition[using:]}"


def queue_artist_song_build() -> None:
    """Queues the bulk build in its own task, so it gets a full task timeout apart from the merge that asked for it."""
    if connection.vendor != "postgresql":
        return
    logger.info("Artist song projection not built: queueing its bulk build")
    try:
        async_task(rebuild_artist_song, only_if_not_ready=True, group=BUILD_GROUP)
    except Exception:
        # Called after the merge committed: failing the task would report merged data as failed.
        logger.exception("Could not queue the artist song build")


def queue_artist_song_build_if_needed() -> None:
    """After a merge: queues the build unless the projection is ready (the merge skipped its sync steps if not)."""
    if connection.vendor == "postgresql" and not ArtistSongState.load().ready:
        queue_artist_song_build()
