from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.bulk_import.BulkImportRun import GENRE_GRAPH_KIND, BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt
from grow.bulk_import.lifecycle import queue_attempt
from grow.genre_graph.bulk_import.GenreGraphImportPayload import GenreGraphImportPayload
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from grow.pipeline_run.link import HEADER
from tests.utils.AppTestCase import AppTestCase

POP = {Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}
UNKNOWN = "00000000-0000-0000-0000-000000000000"
ARTIST_RUNS = reverse("artist-list") + "import-runs/"
TREE_RUNS = reverse("genre-list") + "trees/import-runs/"


class TestPipelineRunImportLink(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

    def _run(self, status_: str = "running") -> PipelineRunRequest:
        return PipelineRunRequest.objects.create(
            kind=PipelineRunRequest.Kind.FULL, status=status_, heartbeat_on=timezone.now()
        )

    def _header(self, value) -> dict:
        return {f"HTTP_{HEADER.upper().replace('-', '_')}": str(value)}

    def _latest(self) -> dict:
        response = self.pipeline.get(path=reverse("pipeline-runs-latest"))
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def test_header_links_an_artists_run_to_the_pipeline_run(self):
        run = self._run()

        response = self.pipeline.post(ARTIST_RUNS, data={}, format="json", **self._header(run.uuid))

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert BulkImportRun.objects.get(pk=response.json()["runId"]).pipeline_run_request_id == run.pk

    def test_without_header_the_link_is_null(self):
        response = self.pipeline.post(ARTIST_RUNS, data={}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert BulkImportRun.objects.get(pk=response.json()["runId"]).pipeline_run_request_id is None

    def test_unknown_or_malformed_uuid_then_400_and_no_run(self):
        for value in (UNKNOWN, "not-a-uuid"):
            response = self.pipeline.post(ARTIST_RUNS, data={}, format="json", **self._header(value))
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert not BulkImportRun.objects.exists()

    def test_run_not_running_then_409_and_no_run(self):
        run = self._run("succeeded")

        response = self.pipeline.post(ARTIST_RUNS, data={}, format="json", **self._header(run.uuid))

        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        assert not BulkImportRun.objects.exists()

    def test_trees_import_links_its_attempt(self):
        run = self._run()
        body = {"trees": [{"treeName": "global", "tree": [POP]}]}

        response = self.api_client.post(TREE_RUNS, data=body, format="json", **self._header(run.uuid))

        assert response.status_code == status.HTTP_202_ACCEPTED, response.content
        assert ImportAttempt.objects.get().pipeline_run_request_id == run.pk

    def test_queue_attempt_copies_the_link_to_each_attempt(self):
        run = self._run()
        import_run = BulkImportRun.objects.create(kind="songs", pipeline_run_request=run)

        first = queue_attempt(import_run)
        second = queue_attempt(import_run)

        assert (first.attempt, second.attempt) == (1, 2)
        assert {first.pipeline_run_request_id, second.pipeline_run_request_id} == {run.pk}

    def test_latest_without_import_has_null_active_import(self):
        self._run()

        body = self._latest()

        assert body["activeImport"] is None
        assert "typicalStageSeconds" in body

    def test_latest_exposes_the_newest_attempt_and_survives_run_cleanup(self):
        run = self._run()
        import_run = BulkImportRun.objects.create(kind="songs", pipeline_run_request=run)
        queue_attempt(import_run)
        ImportAttempt.objects.update(queued_at=timezone.now() - timedelta(minutes=5))
        retry = queue_attempt(import_run)
        import_run.delete()

        body = self._latest()

        assert body["activeImport"]["attempt"] == 2
        assert body["activeImport"]["taskId"] == retry.task_id
        assert body["activeImport"]["bootstrap"] is None
        assert {"kind", "state", "completedSteps", "step"} <= set(body["activeImport"])

    def test_latest_marks_a_first_graph_import_as_bootstrap(self):
        run = self._run()
        for expected, bootstrap in ((None, True), ("00000000-0000-0000-0000-000000000001", False)):
            ImportAttempt.objects.all().delete()
            BulkImportRun.objects.all().delete()
            import_run = BulkImportRun.objects.create(kind=GENRE_GRAPH_KIND, pipeline_run_request=run)
            GenreGraphImportPayload.objects.create(run_id=import_run.pk, payload={"expected_revision": expected})
            queue_attempt(import_run)

            assert self._latest()["activeImport"]["bootstrap"] is bootstrap

    def test_latest_query_count_does_not_grow_with_attempts(self):
        run = self._run()
        import_run = BulkImportRun.objects.create(kind="songs", pipeline_run_request=run)
        queue_attempt(import_run)
        with CaptureQueriesContext(connection) as one:
            self._latest()

        queue_attempt(import_run)
        queue_attempt(import_run)
        with CaptureQueriesContext(connection) as three:
            self._latest()

        assert len(three) == len(one)
