from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.bulk_import.lifecycle import execute_merge, queue_attempt
from grow.bulk_import.progress import ProgressReporter, report_step
from grow.bulk_import.status import progress_payload
from grow.model.import_run.ImportRun import ImportRun
from grow.track.bulk_import.SongImportStaging import SongImportStaging

pytestmark = pytest.mark.django_db(transaction=True)


def make_attempt():
    run = BulkImportRun.objects.create(kind="songs", committed_on=timezone.now())
    return run, queue_attempt(run)


def write_data():
    with report_step("test_write") as timing:
        ImportRun.objects.create(kind="songs", count=3)
        timing["rowcount"] = 3
    return {"imported": 3, "skipped": 0}


def test_success_survives_run_cleanup_and_duplicate_delivery():
    run, attempt = make_attempt()
    result = execute_merge(run.pk, attempt.pk, SongImportStaging, write_data)
    assert not BulkImportRun.objects.filter(pk=run.pk).exists()
    attempt.refresh_from_db()
    assert attempt.state == "succeeded"
    assert attempt.data_applied
    assert attempt.result == result
    assert attempt.completed_steps[0]["label"] == "test_write"
    assert execute_merge(run.pk, attempt.pk, SongImportStaging, write_data) == result
    assert ImportRun.objects.count() == 1


def test_sql_failure_rolls_back_data_and_retains_trace():
    run, attempt = make_attempt()

    def fail():
        write_data()
        raise ValueError("sensitive SQL input")

    with pytest.raises(ValueError, match="sensitive"):
        execute_merge(run.pk, attempt.pk, SongImportStaging, fail)
    attempt.refresh_from_db()
    assert attempt.state == "failed"
    assert not attempt.data_applied
    assert not ImportRun.objects.exists()
    assert not ImportReceipt.objects.exists()
    assert "sensitive" not in attempt.error
    assert attempt.completed_steps[0]["rowcount"] == 3


def test_commit_failure_does_not_claim_data_applied():
    run, attempt = make_attempt()
    with (
        patch.object(connection, "commit", side_effect=DatabaseError("commit failed")),
        pytest.raises(DatabaseError, match="commit failed"),
    ):
        execute_merge(run.pk, attempt.pk, SongImportStaging, write_data)
    attempt.refresh_from_db()
    assert attempt.state == "failed"
    assert not attempt.data_applied
    assert not ImportReceipt.objects.exists()
    assert not ImportRun.objects.exists()


def test_cleanup_failure_after_commit_keeps_receipt():
    run, attempt = make_attempt()
    with (
        patch("django.db.models.query.QuerySet.delete", side_effect=RuntimeError("cleanup failed")),
        pytest.raises(RuntimeError, match="cleanup failed"),
    ):
        execute_merge(run.pk, attempt.pk, SongImportStaging, write_data)
    attempt.refresh_from_db()
    assert attempt.state == "failed"
    assert attempt.data_applied
    assert attempt.result["imported"] == 3
    assert ImportReceipt.objects.filter(pk=run.pk).exists()
    assert execute_merge(run.pk, attempt.pk, SongImportStaging, write_data)["imported"] == 3
    assert ImportRun.objects.count() == 1


def test_old_reporter_cannot_reactivate_interrupted_attempt():
    run, attempt = make_attempt()
    reporter = ProgressReporter(attempt)
    ImportAttempt.objects.filter(pk=attempt.pk).update(state="interrupted", finished_at=timezone.now())
    newer = queue_attempt(run)
    reporter.publish(state="running")
    attempt.refresh_from_db()
    newer.refresh_from_db()
    assert attempt.state == "interrupted"
    assert newer.state == "queued"
    assert newer.attempt == 2


def test_stale_heartbeat_is_distinct_from_progress():
    _, attempt = make_attempt()
    attempt.state = "running"
    attempt.heartbeat_at = timezone.now() - timedelta(seconds=91)
    attempt.last_progress_at = timezone.now() - timedelta(hours=1)
    assert progress_payload(attempt)["observability_stale"]
    attempt.heartbeat_at = timezone.now()
    assert not progress_payload(attempt)["observability_stale"]


def test_retention_keeps_active_attempts_and_recent_results():
    run, attempt = make_attempt()
    ImportAttempt.objects.filter(pk=attempt.pk).update(finished_at=timezone.now() - timedelta(days=31), state="failed")
    run.delete()
    recent = queue_attempt(BulkImportRun.objects.create(kind="songs"))
    assert not ImportAttempt.objects.filter(pk=attempt.pk).exists()
    queue_attempt(BulkImportRun.objects.create(kind="artists"))
    assert ImportAttempt.objects.filter(pk=recent.pk).exists()


def test_reporter_initialization_failure_prevents_business_writes():
    run, attempt = make_attempt()
    with (
        patch.object(ProgressReporter, "start", side_effect=RuntimeError("configuration")),
        pytest.raises(RuntimeError, match="configuration"),
    ):
        execute_merge(run.pk, attempt.pk, SongImportStaging, write_data)
    assert not ImportRun.objects.exists()
    assert BulkImportRun.objects.filter(pk=run.pk).exists()


def test_receipt_path_finalizes_without_merging():
    run, attempt = make_attempt()
    ImportReceipt.objects.create(run_id=run.pk, result={"imported": 4})
    merge = Mock(side_effect=AssertionError("must not merge"))
    invalidate = Mock()
    assert execute_merge(run.pk, attempt.pk, SongImportStaging, merge, invalidate) == {"imported": 4}
    merge.assert_not_called()
    invalidate.assert_called_once()
    assert not BulkImportRun.objects.filter(pk=run.pk).exists()
    attempt.refresh_from_db()
    assert attempt.state == "succeeded"
    assert attempt.data_applied
    assert attempt.result == {"imported": 4}


def test_receipt_path_marks_run_started_before_reporting():
    run, attempt = make_attempt()
    BulkImportRun.objects.filter(pk=run.pk).update(started_on=None)
    ImportReceipt.objects.create(run_id=run.pk, result={"imported": 4})
    with (
        patch("grow.bulk_import.lifecycle.ProgressReporter.start", side_effect=RuntimeError("worker died")),
        pytest.raises(RuntimeError),
    ):
        execute_merge(run.pk, attempt.pk, SongImportStaging, Mock())
    assert BulkImportRun.objects.get(pk=run.pk).started_on is not None
