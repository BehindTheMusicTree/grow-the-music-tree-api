import logging
from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection
from django.utils import timezone

from grow.bulk_import.BulkImportRun import BulkImportRun

logger = logging.getLogger(__name__)

IMPORT_LOCK_KEY = 0x696D7072  # pg advisory lock namespace, "impr"; the run id is the second key


@contextmanager
def hold_merge_lock(run_id: int) -> Iterator[None]:
    """
    Holds a session advisory lock on the run for the whole merge and stamps `started_on`. A worker killed mid-merge
    (e.g. a redeploy) drops its connection and with it the lock, which is how `merge_was_lost` tells a dead merge
    from a running one.
    """
    if connection.vendor != "postgresql":  # the tests' in-memory SQLite has no advisory locks
        yield
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s, %s)", [IMPORT_LOCK_KEY, run_id])
    try:
        BulkImportRun.objects.filter(pk=run_id).update(started_on=timezone.now())
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [IMPORT_LOCK_KEY, run_id])


def claim_lost_merge(run_id: int, kind: str) -> BulkImportRun | None:
    """
    The run if its merge started, holds no lock (its worker died) and this caller won the right to enqueue it again,
    else None. Resets `started_on`, so concurrent pollers enqueue it once.
    """
    if connection.vendor != "postgresql":
        return None
    run = BulkImportRun.objects.filter(pk=run_id, kind=kind, started_on__isnull=False).first()
    if run is None:
        return None
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [IMPORT_LOCK_KEY, run_id])
        (free,) = cursor.fetchone()
        if not free:
            return None
        cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [IMPORT_LOCK_KEY, run_id])
    if not BulkImportRun.objects.filter(pk=run_id, started_on=run.started_on).update(started_on=None):
        return None
    logger.warning("import run %s: merge lost to a worker restart, enqueueing it again", run_id)
    return run
