import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.db import connection, models, transaction
from django.utils import timezone

from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.bulk_import.merge_lock import hold_merge_lock
from grow.bulk_import.progress import ProgressReporter, activate, committed, committing, deactivate, report_step

logger = logging.getLogger(__name__)


def queue_attempt(run: BulkImportRun) -> ImportAttempt:
    cutoff = timezone.now() - timedelta(days=30)
    ImportAttempt.objects.filter(finished_at__lt=cutoff).exclude(run_id__in=BulkImportRun.objects.values("pk")).delete()
    ImportReceipt.objects.filter(applied_at__lt=cutoff).exclude(run_id__in=BulkImportRun.objects.values("pk")).delete()
    number = (ImportAttempt.objects.filter(run_id=run.pk).aggregate(n=models.Max("attempt"))["n"] or 0) + 1
    return ImportAttempt.objects.create(
        run_id=run.pk, task_id=f"import-run-{run.pk}", kind=run.kind, mode=run.mode, user_id=run.user_id, attempt=number
    )


def _finalize(
    run_id: int,
    staging_model: type[models.Model],
    invalidate: Callable[[], Any] | None,
    reporter: ProgressReporter,
) -> None:
    """Post-commit work, idempotent so a later attempt can redo it: cache invalidation, then staging cleanup."""
    try:
        if invalidate is not None:
            with report_step("invalidate_cache"):
                invalidate()
    finally:
        reporter.publish(state=ImportAttempt.State.CLEANING_UP)
        with report_step("cleanup"):
            staging_model._default_manager.filter(run_id=run_id).delete()
            BulkImportDeletion.objects.filter(run_id=run_id).delete()
            BulkImportRun.objects.filter(pk=run_id).delete()


def execute_merge(
    run_id: int,
    attempt_id: int | None,
    staging_model: type[models.Model],
    merge: Callable[[], dict[str, Any]],
    invalidate: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    with hold_merge_lock(run_id):
        # The receipt and the data commit together, even if the worker dies before publishing its result.
        receipt = ImportReceipt.objects.filter(pk=run_id).first()
        if receipt is not None:
            # Data already applied: a queued attempt only finalizes (invalidate + cleanup), it never merges again.
            attempt = ImportAttempt.objects.filter(pk=attempt_id, run_id=run_id).first() if attempt_id else None
            if attempt is None or attempt.state != ImportAttempt.State.QUEUED:
                return receipt.result
        else:
            run = BulkImportRun.objects.get(pk=run_id)
            attempt = (
                ImportAttempt.objects.get(pk=attempt_id, run_id=run_id)
                if attempt_id is not None
                else ImportAttempt.objects.filter(run_id=run_id).order_by("-attempt").first() or queue_attempt(run)
            )
        if attempt.state != ImportAttempt.State.QUEUED:
            raise ValueError(f"import run {run_id} attempt {attempt.attempt} is already {attempt.state}")
        latest = ImportAttempt.objects.filter(run_id=run_id).order_by("-attempt").first()
        if latest is None or latest.pk != attempt.pk:
            raise ValueError(f"import run {run_id} attempt {attempt.attempt} is superseded")
        BulkImportRun.objects.filter(pk=run_id).update(started_on=timezone.now())
        reporter = ProgressReporter(attempt)
        reporter.start()
        token = activate(reporter)
        applied = receipt is not None
        result = receipt.result if receipt is not None else None
        try:
            backend = {}
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pid, backend_start FROM pg_stat_activity WHERE pid = pg_backend_pid()")
                    pid, backend_start = cursor.fetchone()
                backend = {"backend_pid": pid, "backend_start": backend_start}
            reporter.publish(state=ImportAttempt.State.RUNNING, started_at=timezone.now(), **backend)
            if receipt is not None:
                reporter.publish(data_applied=True, result=result)
            else:
                try:
                    with transaction.atomic():
                        result = merge()
                        ImportReceipt.objects.create(run_id=run_id, result=result)
                        committing()
                except BaseException:
                    _finalize(run_id, staging_model, None, reporter)
                    raise
                applied = True
                committed()
                reporter.publish(data_applied=True, result=result)
            _finalize(run_id, staging_model, invalidate, reporter)
            reporter.publish(
                state=ImportAttempt.State.SUCCEEDED, result=result, data_applied=True, finished_at=timezone.now()
            )
            return result
        except BaseException as exc:
            # Do not expose database exceptions (which can include SQL and input values) through the status endpoint.
            logger.exception("import run %s attempt %s failed (data_applied=%s)", run_id, attempt.attempt, applied)
            reporter.publish(
                state=ImportAttempt.State.FAILED,
                data_applied=applied,
                result=result if applied else None,
                error=f"{type(exc).__name__}: import {'post-commit processing' if applied else 'merge'} failed; see worker logs",
                finished_at=timezone.now(),
            )
            raise
        finally:
            deactivate(token)
            reporter.close()
