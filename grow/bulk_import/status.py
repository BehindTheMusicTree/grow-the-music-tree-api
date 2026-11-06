import logging
from typing import Any

from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from django_q.models import Task

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.bulk_import.lifecycle import queue_attempt
from grow.bulk_import.merge_lock import IMPORT_LOCK_KEY
from grow.bulk_import.progress import TERMINAL_STATES

logger = logging.getLogger(__name__)


def sql_activity(attempt: ImportAttempt) -> dict[str, Any]:
    if connection.vendor != "postgresql" or attempt.backend_pid is None:
        return {"availability": "unavailable"}
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "SELECT state, EXTRACT(EPOCH FROM (clock_timestamp() - query_start)), wait_event_type,"
                " cardinality(pg_blocking_pids(pid)) FROM pg_stat_activity WHERE pid = %s AND backend_start = %s",
                [attempt.backend_pid, attempt.backend_start],
            )
            row = cursor.fetchone()
        if row is None:
            return {"availability": "available", "session_present": False}
        state, age, wait, blockers = row
        if state is None:
            return {"availability": "unavailable"}
        return {
            "availability": "available",
            "session_present": True,
            "state": state,
            "query_age_seconds": max(0, float(age)) if age is not None else None,
            "wait_event_type": wait,
            "blocker_count": blockers,
        }
    except DatabaseError:
        logger.warning("import run %s SQL diagnostic unavailable", attempt.run_id, exc_info=True)
        return {"availability": "unavailable"}


def progress_payload(attempt: ImportAttempt):
    fields = (
        "run_id",
        "task_id",
        "kind",
        "mode",
        "attempt",
        "state",
        "queued_at",
        "started_at",
        "finished_at",
        "step",
        "step_started_at",
        "last_progress_at",
        "heartbeat_at",
        "completed_steps",
        "data_applied",
    )
    payload = {field: getattr(attempt, field) for field in fields}
    payload["sql"] = sql_activity(attempt) if attempt.state not in TERMINAL_STATES else {"availability": "unavailable"}
    payload["observability_stale"] = attempt.state not in (*TERMINAL_STATES, "queued") and (
        attempt.heartbeat_at is None or (timezone.now() - attempt.heartbeat_at).total_seconds() >= 90
    )
    return payload


def reconcile(attempt: ImportAttempt) -> ImportAttempt | None:
    """Only disappearance of the session lock permits recovery; heartbeat age is never evidence of death."""
    if attempt.state in TERMINAL_STATES:
        receipt = ImportReceipt.objects.filter(pk=attempt.run_id).first()
        if receipt is not None and not attempt.data_applied:
            ImportAttempt.objects.filter(pk=attempt.pk).update(
                data_applied=True,
                result=receipt.result,
                error="Data committed; inspect worker logs and cleanup before continuing",
            )
        return None
    if connection.vendor != "postgresql":
        return None
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [IMPORT_LOCK_KEY, attempt.run_id])
        if not cursor.fetchone()[0]:
            return None
    try:
        with transaction.atomic():
            current = ImportAttempt.objects.select_for_update().get(pk=attempt.pk)
            if current.state in TERMINAL_STATES:
                return None
            receipt = ImportReceipt.objects.filter(pk=attempt.run_id).first()
            run = BulkImportRun.objects.filter(pk=attempt.run_id).first()
            task = Task.objects.filter(group=attempt.task_id).order_by("-stopped").first()
            if task is not None and (task.kwargs or {}).get("attempt_id") != attempt.pk:
                task = None
            if current.state == "queued" and task is None and (run is None or run.started_on is None):
                return None
            if receipt is not None:
                current.state = (
                    ImportAttempt.State.SUCCEEDED if task is not None and task.success else ImportAttempt.State.FAILED
                )
                current.data_applied = True
                current.result = receipt.result
                current.error = (
                    None
                    if current.state == ImportAttempt.State.SUCCEEDED
                    else "Worker stopped after data commit; inspect cleanup before continuing"
                )
            elif task is not None:
                current.state = ImportAttempt.State.SUCCEEDED if task.success else ImportAttempt.State.FAILED
                current.result = task.result if task.success else None
                current.error = None if task.success else "Import failed; see worker logs"
            else:
                current.state = ImportAttempt.State.INTERRUPTED
                current.error = "Worker session ended before a durable result was recorded"
            current.finished_at = timezone.now()
            current.save()
            if receipt is None and task is None and run is not None:
                BulkImportRun.objects.filter(pk=run.pk).update(started_on=None)
                return queue_attempt(run)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [IMPORT_LOCK_KEY, attempt.run_id])
    return None
