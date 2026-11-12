import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections
from django.test import override_settings
from django.utils import timezone
from django_q.models import Task

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.bulk_import.lifecycle import execute_merge, queue_attempt
from grow.bulk_import.merge_lock import IMPORT_LOCK_KEY
from grow.bulk_import.progress import ProgressReporter, report_step
from grow.bulk_import.status import MAX_ATTEMPTS, reconcile, sql_activity
from grow.model.import_run.ImportRun import ImportRun
from grow.track.bulk_import.SongImportStaging import SongImportStaging

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.01)
    raise AssertionError(f"condition was not visible within {timeout} seconds")


def attempt_step(attempt_id):
    return ImportAttempt.objects.get(pk=attempt_id).step


def test_reporter_visible_before_commit_and_heartbeat_continues_during_sql_lock(settings):
    settings.IMPORT_PROGRESS_THREADED = True
    run = BulkImportRun.objects.create(kind="songs", committed_on=timezone.now())
    attempt = queue_attempt(run)
    errors = []

    def merge():
        with report_step("locked_write"):
            ImportRun.objects.create(kind="songs", count=1)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(78319)")
        return {"imported": 1}

    def worker():
        try:
            execute_merge(run.pk, attempt.pk, SongImportStaging, merge)
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(78319)")
    thread = threading.Thread(target=worker)
    try:
        with patch("grow.bulk_import.progress.HEARTBEAT_SECONDS", 0.05):
            thread.start()
            wait_for(lambda: attempt_step(attempt.pk) == "locked_write")
            attempt.refresh_from_db()
            heartbeat = attempt.heartbeat_at
            wait_for(lambda: ImportAttempt.objects.get(pk=attempt.pk).heartbeat_at > heartbeat)
            assert ImportRun.objects.count() == 0
            attempt.refresh_from_db()
            diagnostic = wait_for(
                lambda: sql_activity(attempt) if sql_activity(attempt).get("blocker_count") == 1 else None
            )
            assert diagnostic["wait_event_type"] == "Lock"
            # Even a deliberately stale heartbeat must not trigger a retry while the session holds its lock.
            attempt.heartbeat_at = timezone.now() - timedelta(hours=1)
            assert reconcile(attempt) is None
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(78319)")
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert errors == []
    attempt.refresh_from_db()
    assert attempt.state == "succeeded"
    assert ImportRun.objects.count() == 1


def test_lost_worker_recovers_once_and_fences_old_reporter():
    run = BulkImportRun.objects.create(kind="songs", started_on=timezone.now(), committed_on=timezone.now())
    attempt = queue_attempt(run)
    attempt.state = "running"
    attempt.save()
    retry = reconcile(attempt)
    assert retry.attempt == 2
    assert reconcile(attempt) is None
    reporter = ProgressReporter(attempt)
    reporter.publish(state="running")
    attempt.refresh_from_db()
    assert attempt.state == "interrupted"
    assert ImportAttempt.objects.filter(run_id=run.pk).count() == 2


def test_commit_receipt_prevents_retry_during_result_persistence_gap():
    run = BulkImportRun.objects.create(kind="songs", started_on=timezone.now(), committed_on=timezone.now())
    attempt = queue_attempt(run)
    attempt.state = "committing"
    attempt.save()
    ImportReceipt.objects.create(run_id=run.pk, result={"imported": 12})
    run.delete()
    assert reconcile(attempt) is None
    attempt.refresh_from_db()
    assert attempt.data_applied
    assert attempt.result == {"imported": 12}
    assert attempt.state == "succeeded"
    assert ImportAttempt.objects.count() == 1


def test_reporter_outage_does_not_rollback_business_transaction(settings):
    settings.IMPORT_PROGRESS_THREADED = True
    run = BulkImportRun.objects.create(kind="songs", committed_on=timezone.now())
    attempt = queue_attempt(run)

    def merge():
        with report_step("write"):
            ImportRun.objects.create(kind="songs", count=1)
        return {"imported": 1}

    with patch.object(ProgressReporter, "_write", side_effect=RuntimeError("telemetry unavailable")):
        result = execute_merge(run.pk, attempt.pk, SongImportStaging, merge)
    assert result == {"imported": 1}
    assert ImportRun.objects.count() == 1
    assert ImportReceipt.objects.filter(pk=run.pk).exists()


def test_sql_diagnostic_unavailable_does_not_imply_worker_dead():
    run = BulkImportRun.objects.create(kind="songs")
    attempt = queue_attempt(run)
    attempt.backend_pid = 999999999
    attempt.backend_start = timezone.now()
    assert sql_activity(attempt) == {"availability": "available", "session_present": False}
    with patch("grow.bulk_import.status.connection.cursor", side_effect=DatabaseError):
        assert sql_activity(attempt) == {"availability": "unavailable"}


@pytest.mark.parametrize("after_commit", [False, True])
def test_sigkill_reconciles_transaction_and_never_replays_applied_data(after_commit):
    run = BulkImportRun.objects.create(kind="songs", committed_on=timezone.now())
    attempt = queue_attempt(run)
    database_url = urlsplit(os.environ["POSTGRES_TEST_DATABASE_URL"])
    database_url = database_url._replace(path="/" + connection.settings_dict["NAME"]).geturl()
    program = """
import sys, time, django
django.setup()
from django.conf import settings
settings.IMPORT_PROGRESS_THREADED = True
from grow.bulk_import.lifecycle import execute_merge
from grow.bulk_import.progress import report_step
from grow.model.import_run.ImportRun import ImportRun
from grow.track.bulk_import.SongImportStaging import SongImportStaging

def pause():
    while True:
        time.sleep(1)

def merge():
    with report_step("waiting_for_kill"):
        ImportRun.objects.create(kind="songs", count=1)
        if sys.argv[3] == "False":
            pause()
    return {"imported": 1}

execute_merge(int(sys.argv[1]), int(sys.argv[2]), SongImportStaging, merge, pause)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(run.pk), str(attempt.pk), str(after_commit)],
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "tests.postgres_settings",
            "POSTGRES_TEST_DATABASE_URL": database_url,
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        # A fresh Django interpreter needs more time than an event from an already running reporter.
        def reached_pause():
            if process.poll() is not None:
                raise AssertionError(f"worker exited before pause: {process.communicate()[1].decode()}")
            return attempt_step(attempt.pk) == ("invalidate_cache" if after_commit else "waiting_for_kill")

        wait_for(reached_pause, timeout=30)
        attempt.refresh_from_db()
    finally:
        process.kill()
        process.communicate(timeout=5)
    wait_for(lambda: sql_activity(attempt).get("session_present") is False)
    retry = reconcile(attempt)
    attempt.refresh_from_db()
    assert attempt.data_applied == after_commit
    if after_commit:
        assert retry.attempt == 2
        assert attempt.state == "interrupted"
        assert ImportRun.objects.count() == 1
        merge = Mock(side_effect=AssertionError("applied data must never be merged again"))
        invalidate = Mock()
        result = execute_merge(run.pk, retry.pk, SongImportStaging, merge, invalidate)
        assert result == {"imported": 1}
        merge.assert_not_called()
        invalidate.assert_called_once()
        assert not BulkImportRun.objects.filter(pk=run.pk).exists()
        assert ImportRun.objects.count() == 1
        retry.refresh_from_db()
        assert retry.state == "succeeded"
    else:
        assert retry.attempt == 2
        assert attempt.state == "interrupted"
        assert not ImportRun.objects.exists()


def applied_run(state="running", error=None):
    run = BulkImportRun.objects.create(kind="songs", started_on=timezone.now(), committed_on=timezone.now())
    attempt = queue_attempt(run)
    attempt.state = state
    attempt.error = error
    attempt.save()
    ImportReceipt.objects.create(run_id=run.pk, result={"imported": 12})
    return run, attempt


def test_worker_lost_after_commit_queues_a_finalizing_attempt():
    run, attempt = applied_run()
    retry = reconcile(attempt)
    assert retry.attempt == 2
    attempt.refresh_from_db()
    assert attempt.state == "interrupted"
    assert attempt.data_applied
    BulkImportRun.objects.get(pk=run.pk)


def test_worker_lost_after_commit_with_run_already_cleaned_succeeds():
    run, attempt = applied_run()
    run.delete()
    assert reconcile(attempt) is None
    attempt.refresh_from_db()
    assert attempt.state == "succeeded"
    assert attempt.result == {"imported": 12}


def test_failed_task_after_commit_stays_failed():
    run, attempt = applied_run()
    Task.objects.create(
        id="t1",
        name="t1",
        func="x",
        group=attempt.task_id,
        kwargs={"attempt_id": attempt.pk},
        started=timezone.now(),
        stopped=timezone.now(),
        success=False,
    )
    assert reconcile(attempt) is None
    attempt.refresh_from_db()
    assert attempt.state == "failed"
    assert BulkImportRun.objects.filter(pk=run.pk).exists()


def test_finalization_gives_up_after_max_attempts():
    _run, attempt = applied_run()
    ImportAttempt.objects.filter(pk=attempt.pk).update(attempt=MAX_ATTEMPTS)
    attempt.refresh_from_db()
    assert reconcile(attempt) is None
    attempt.refresh_from_db()
    assert attempt.state == "failed"
    assert "gave up" in attempt.error


def test_terminal_worker_stopped_attempt_is_resumed():
    _run, attempt = applied_run("failed", "Worker stopped after data commit; inspect cleanup before continuing")
    retry = reconcile(attempt)
    assert retry.attempt == 2
    attempt.refresh_from_db()
    assert attempt.state == "interrupted"
    assert reconcile(attempt) is None


def test_terminal_real_failure_is_not_resumed():
    run, attempt = applied_run("failed", "Import failed; see worker logs")
    assert reconcile(attempt) is None
    assert ImportAttempt.objects.filter(run_id=run.pk).count() == 1


def hold_lock(run_id):
    conn = connections["default"].copy()
    cursor = conn.cursor()
    cursor.execute("SELECT pg_advisory_lock(%s, %s)", [IMPORT_LOCK_KEY, run_id])
    return conn


def test_drain_returns_when_nothing_is_active():
    call_command("wait_for_import_drain", timeout=1, interval=1)


def test_drain_ignores_dead_worker():
    applied_run("running")
    call_command("wait_for_import_drain", timeout=1, interval=1)


def test_drain_fails_at_timeout_while_a_lock_is_held():
    run, _ = applied_run("running")
    conn = hold_lock(run.pk)
    try:
        with pytest.raises(CommandError, match=f"run={run.pk}"):
            call_command("wait_for_import_drain", timeout=1, interval=1)
    finally:
        conn.close()
    call_command("wait_for_import_drain", timeout=1, interval=1)


def test_drain_waits_for_a_queued_finalization():
    run, _ = applied_run("queued")
    with pytest.raises(CommandError, match=f"run={run.pk}"):
        call_command("wait_for_import_drain", timeout=1, interval=1)


def test_drain_ignores_a_queued_attempt_without_receipt():
    run = BulkImportRun.objects.create(kind="songs", started_on=timezone.now(), committed_on=timezone.now())
    queue_attempt(run)
    call_command("wait_for_import_drain", timeout=1, interval=1)
