"""Approved per-side preparation of a restored catalogue, run as ``grow_perf_owner`` inside the side's image.

The same file prepares the base and the head code, so it only calls management commands that both versions ship;
the base must already contain `verify_song_membership`.
It stops at the first failure: a half-prepared database must never be measured. Order matters: the cheap
derivation check runs before hours of projection rebuilds, and the count repairs run after the rebuilds.
"""

import sys
import time

import django
from django.core.management import call_command
from django.db import connection

POSTGRES_MAJOR = 16


def log(message: str) -> None:
    sys.stdout.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
    sys.stdout.flush()


def step(label: str, command: str, *arguments: str) -> None:
    log(f"start {label}")
    started = time.monotonic()
    call_command(command, *arguments)
    log(f"done {label} in {time.monotonic() - started:.1f}s")


def require_postgres() -> None:
    if connection.vendor != "postgresql":
        raise SystemExit(f"PostgreSQL required, got {connection.vendor}")
    version = connection.cursor().connection.info.server_version
    if not POSTGRES_MAJOR * 10000 <= version < (POSTGRES_MAJOR + 1) * 10000:
        raise SystemExit(f"PostgreSQL {POSTGRES_MAJOR} required, got server_version_num {version}")


def vacuum_analyze() -> None:
    """PostgreSQL 16 restores no planner statistics and no visibility map: both shape the measured plans."""
    log("start VACUUM (ANALYZE)")
    started = time.monotonic()
    with connection.cursor() as cursor:
        cursor.execute("SELECT quote_ident(tablename) FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f"VACUUM (ANALYZE) public.{table}")
        cursor.execute(
            "SELECT relname FROM pg_stat_user_tables WHERE schemaname = 'public' AND last_analyze IS NULL ORDER BY 1"
        )
        missing = [row[0] for row in cursor.fetchall()]
    if missing:
        raise SystemExit(f"tables without planner statistics after ANALYZE: {', '.join(missing)}")
    log(f"done VACUUM (ANALYZE) of {len(tables)} tables in {time.monotonic() - started:.1f}s")


def main() -> None:
    django.setup()
    require_postgres()
    connection.ensure_connection()
    step("migrate", "migrate", "--no-input")
    step("verify song membership", "verify_song_membership")
    # A command without --if-stale fails on the unknown option: an old image has no fingerprint, so no fallback.
    step("rebuild song search", "rebuild_song_search", "--if-stale")
    step("rebuild artist song", "rebuild_artist_song", "--if-stale")
    step("repair genre membership counts", "verify_genre_membership_counts", "--repair")
    step("repair genre catalogue counts", "verify_genre_catalogue_counts", "--repair")
    vacuum_analyze()
    log("preparation complete")


if __name__ == "__main__":
    main()
