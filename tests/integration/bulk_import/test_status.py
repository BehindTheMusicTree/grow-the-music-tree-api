from unittest.mock import patch

from django.urls import reverse
from django_q.models import Task
from rest_framework.test import APIClient

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt
from grow.bulk_import.lifecycle import queue_attempt
from tests.utils.AppTestCase import AppTestCase

PREFIX = reverse("song-list") + "songs/"


class TestProgressStatus(AppTestCase):
    def setUp(self):
        super().setUp()
        self.run = BulkImportRun.objects.create(kind="songs")
        self.attempt = queue_attempt(self.run)
        self.path = f"{PREFIX}import/{self.attempt.task_id}/status/"

    def test_admin_gets_camel_case_diagnostic_without_sql(self):
        response = self.api_client.get(self.path)
        data = response.json()
        assert data["status"] == "pending"
        assert data["progress"]["runId"] == self.run.pk
        assert data["progress"]["queuedAt"]
        assert data["progress"]["sql"] == {"availability": "unavailable"}
        assert "query" not in response.content.decode().lower()

    def test_public_gets_no_progress_and_cannot_trigger_recovery(self):
        with patch("grow.view.viewset.mixin.BulkImportRunMixin.reconcile") as recover:
            response = APIClient().get(self.path)
        assert response.json() == {"status": "pending"}
        recover.assert_not_called()

    def test_other_kind_cannot_read_attempt(self):
        self.attempt.kind = "artists"
        self.attempt.save()
        assert self.api_client.get(self.path).json() == {"status": "pending"}

    def test_terminal_attempt_survives_missing_django_q_result(self):
        ImportAttempt.objects.filter(pk=self.attempt.pk).update(state="succeeded", result={"imported": 2})
        response = self.api_client.get(self.path).json()
        assert response["status"] == "success"
        assert response["result"] == {"imported": 2}
        assert not Task.objects.exists()

    def test_failed_post_commit_attempt_exposes_data_applied(self):
        ImportAttempt.objects.filter(pk=self.attempt.pk).update(
            state="failed", data_applied=True, error="cleanup failed"
        )
        response = self.api_client.get(self.path).json()
        assert response["status"] == "failed"
        assert response["progress"]["dataApplied"]
        assert response["error"] == "cleanup failed"

    def test_enqueue_failure_is_durable(self):
        with patch("grow.view.viewset.mixin.BulkImportRunMixin.async_task", side_effect=RuntimeError("broker down")):
            response = self.api_client.post(f"{PREFIX}import-runs/{self.run.pk}/commit/")
        assert response.status_code == 500
        attempt = ImportAttempt.objects.filter(run_id=self.run.pk).latest("attempt")
        assert attempt.state == "failed"
        assert "enqueue" in attempt.error

    def test_recovery_enqueue_failure_is_durable(self):
        retry = queue_attempt(self.run)
        with (
            patch("grow.view.viewset.mixin.BulkImportRunMixin.reconcile", return_value=retry),
            patch("grow.view.viewset.mixin.BulkImportRunMixin.async_task", side_effect=RuntimeError("broker down")),
        ):
            response = self.api_client.get(self.path)
        assert response.status_code == 500
        retry.refresh_from_db()
        assert retry.state == "failed"
        assert retry.finished_at is not None
        assert "enqueue" in retry.error
        assert self.api_client.get(self.path).json()["status"] == "failed"

    def test_legacy_recovery_enqueue_failure_is_durable(self):
        ImportAttempt.objects.all().delete()
        with (
            patch("grow.view.viewset.mixin.BulkImportRunMixin.claim_lost_merge", return_value=self.run),
            patch("grow.view.viewset.mixin.BulkImportRunMixin.async_task", side_effect=RuntimeError("broker down")),
        ):
            response = self.api_client.get(self.path)
        assert response.status_code == 500
        attempt = ImportAttempt.objects.get(run_id=self.run.pk)
        assert attempt.state == "failed"
        assert self.api_client.get(self.path).json()["status"] == "failed"
