import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from django.db import DatabaseError, connection, connections
from django.test import override_settings
from django.utils import timezone

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.bulk_import.lifecycle import execute_merge, queue_attempt
from grow.bulk_import.progress import ProgressReporter, report_step
from grow.bulk_import.status import reconcile, sql_activity
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
    assert attempt.state == "failed"
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
        assert retry is None
        assert ImportRun.objects.count() == 1
        assert execute_merge(run.pk, attempt.pk, SongImportStaging, lambda: {"imported": 999}) == {"imported": 1}
    else:
        assert retry.attempt == 2
        assert attempt.state == "interrupted"
        assert not ImportRun.objects.exists()
