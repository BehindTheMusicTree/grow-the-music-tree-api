import gzip
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

import pytest
from django.conf import settings
from django.db import IntegrityError, connections, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.authentication.Principal import Principal
from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from tests.utils.AppApiClient import ADMIN_EMAIL, AppApiClient
from tests.utils.AppTestCase import AppTestCase
from tests.utils.curation_export import export_curation

ITEM = {"item_id": "Q999999991", "reason": "testing"}
TREE = {
    Fields.TREE_NAME: "global",
    Fields.TREE: [{Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}],
}


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_concurrent_recovery_requests_share_one_uuid():
    source = PipelineRunRequest.objects.create(
        kind="sync", status="failed", manifest_sha256="a" * 64, songs_snapshot_sha256="b" * 64
    )
    ImportAttempt.objects.create(
        pipeline_run_request=source,
        kind="songs",
        mode="full",
        run_id=142,
        task_id="songs-142",
        attempt=1,
        state="succeeded",
        data_applied=True,
    )
    admin = AppApiClient().admin
    start = Barrier(2, timeout=10)

    def submit():
        try:
            client = APIClient()
            client.force_authenticate(user=admin, token=Principal("admin", ADMIN_EMAIL, settings.ADMIN_GOOGLE_SUB))
            start.wait()
            response = client.post(
                reverse("pipeline-runs"),
                data={"kind": "sync_artists", "sourceRunUuid": str(source.uuid)},
                format="json",
            )
            return response.status_code, response.json()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = [executor.submit(submit), executor.submit(submit)]
        results = [response.result(timeout=20) for response in responses]
    assert sorted(code for code, _ in results) == [200, 201], results
    assert results[0][1]["uuid"] == results[1][1]["uuid"]
    assert PipelineRunRequest.objects.filter(source_run=source).count() == 1


class TestPipelineRun(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

    def _edit(self) -> None:
        response = self.api_client.post(
            path=reverse("curation-entries", kwargs={"list_name": "theme_genres"}), data={"row": ITEM}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content

    def _nightly_applies_everything(self) -> None:
        data = {**TREE, "curationExportedOn": export_curation(self.pipeline)}
        response = self.pipeline.post(path=reverse("genre-list") + "tree/import/", data=data, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content

    def _post(self, kind: str):
        return self.api_client.post(path=reverse("pipeline-runs"), data={"kind": kind}, format="json")

    def _request(self, kind: str = "curation") -> dict:
        if kind == "curation":
            self._edit()
        response = self._post(kind)
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.json()

    def _claim(self):
        return self.pipeline.post(path=reverse("pipeline-runs-claim"))

    def _patch(self, uuid: str, data: dict):
        return self.pipeline.patch(path=reverse("pipeline-run", kwargs={"uuid": uuid}), data=data, format="json")

    def _cancel(self, uuid: str, client: APIClient | None = None):
        return (client or self.api_client).post(path=reverse("pipeline-run-cancel", kwargs={"uuid": uuid}))

    def _latest(self):
        return self.pipeline.get(path=reverse("pipeline-runs-latest"))

    def _latest_run(self) -> dict:
        """The latest run without the import progress fields, which have their own tests."""
        body = self._latest().json()
        return {key: value for key, value in body.items() if key not in ("activeImport", "typicalStageSeconds")}

    def _go_silent(self, uuid: str, minutes: int) -> None:
        PipelineRunRequest.objects.filter(uuid=uuid).update(heartbeat_on=timezone.now() - timedelta(minutes=minutes))

    def _failed_gold(self, *, attested: bool = True, applied: bool = True) -> PipelineRunRequest:
        source = PipelineRunRequest.objects.create(
            kind="sync",
            status="failed",
            **({"manifest_sha256": "a" * 64, "songs_snapshot_sha256": "b" * 64} if attested else {}),
        )
        for kind, run_id, data_applied in (("songs", 142, applied), ("region_map", 143, True)):
            ImportAttempt.objects.create(
                pipeline_run_request=source,
                kind=kind,
                mode="full",
                run_id=run_id,
                task_id=f"task-{run_id}",
                attempt=1,
                state="succeeded",
                data_applied=data_applied,
            )
        return source

    def _resume_artists(self, source: PipelineRunRequest, client=None):
        return (client or self.api_client).post(
            path=reverse("pipeline-runs"),
            data={"kind": "sync_artists", "sourceRunUuid": str(source.uuid)},
            format="json",
        )

    def test_artists_recovery_uses_applied_songs_even_when_the_map_is_newer(self):
        source = self._failed_gold()
        history = self.api_client.get(reverse("pipeline-runs")).json()["results"][0]
        assert history["status"] == "failed"
        assert history["artistsRecovery"]["eligible"] is True

        response = self._resume_artists(source)
        assert response.status_code == status.HTTP_201_CREATED, response.content
        duplicate = self._resume_artists(source)
        assert duplicate.status_code == status.HTTP_200_OK
        assert duplicate.json()["uuid"] == response.json()["uuid"]
        claimed = self._claim().json()
        assert claimed["sourceRunUuid"] == str(source.uuid)
        assert claimed["manifestSha256"] == "a" * 64
        assert claimed["songsSnapshotSha256"] == "b" * 64
        source.refresh_from_db()
        assert source.status == "failed"

    def test_artists_recovery_requires_admin_and_a_source(self):
        source = self._failed_gold()
        assert self._resume_artists(source, self.pipeline).status_code == status.HTTP_403_FORBIDDEN
        assert self._post("sync_artists").status_code == status.HTTP_400_BAD_REQUEST

    def test_artists_recovery_rejects_unattested_and_unapplied_sources(self):
        for attested, applied in ((False, True), (True, False)):
            with self.subTest(attested=attested, applied=applied):
                source = self._failed_gold(attested=attested, applied=applied)
                response = self._resume_artists(source)
                assert response.status_code == status.HTTP_409_CONFLICT, response.content
                ImportAttempt.objects.filter(pipeline_run_request=source).delete()

    def test_artists_recovery_rejects_catalogue_replacement_or_live_merge(self):
        source = self._failed_gold()
        attempt = ImportAttempt.objects.create(
            kind="songs", mode="full", run_id=144, task_id="new", attempt=1, state="committing"
        )
        assert self._resume_artists(source).status_code == status.HTTP_409_CONFLICT
        attempt.state = "succeeded"
        attempt.data_applied = True
        attempt.save()
        assert self._resume_artists(source).status_code == status.HTTP_409_CONFLICT

    def test_artists_recovery_conflicts_with_another_active_request(self):
        source = self._failed_gold()
        self._request("sync")
        assert self._resume_artists(source).status_code == status.HTTP_409_CONFLICT

    def test_song_receipt_allows_recovery_unless_another_song_merge_is_pending_on_the_source(self):
        source = self._failed_gold(applied=False)
        ImportAttempt.objects.filter(run_id=142).update(state="committing")
        ImportReceipt.objects.create(run_id=142, result={})
        other = ImportAttempt.objects.create(
            pipeline_run_request=source,
            kind="songs",
            mode="full",
            run_id=141,
            task_id="old",
            attempt=1,
            state="running",
        )
        assert self._resume_artists(source).status_code == 409
        other.delete()
        assert self._resume_artists(source).status_code == 201

    def test_active_recovery_tracks_artist_import_from_the_original_request(self):
        source = self._failed_gold()
        ImportAttempt.objects.create(
            pipeline_run_request=source, kind="artists", mode="full", run_id=144, task_id="artists", attempt=1
        )
        assert self._resume_artists(source).status_code == 201
        assert self._claim().status_code == 200
        assert self._latest().json()["activeImport"]["taskId"] == "artists"

    def test_historical_gold_attestation_is_pipeline_only_and_immutable(self):
        source = self._failed_gold(attested=False)
        url = reverse("pipeline-gold-fingerprints", kwargs={"uuid": source.uuid})
        data = {"manifestSha256": "a" * 64, "songsSnapshotSha256": "b" * 64, "songsRunId": 142}
        assert self.api_client.patch(url, data=data, format="json").status_code == 403
        assert self.pipeline.patch(url, data={**data, "songsRunId": 143}, format="json").status_code == 409
        for _ in range(2):
            response = self.pipeline.patch(url, data=data, format="json")
            assert response.status_code == 204, response.content
        conflict = self.pipeline.patch(url, data={**data, "manifestSha256": "c" * 64}, format="json")
        assert conflict.status_code == 409, conflict.content
        assert self._resume_artists(source).status_code == 201

    def test_recovery_execution_rechecks_catalogue_replacement(self):
        source = self._failed_gold()
        uuid = self._resume_artists(source).json()["uuid"]
        assert self._claim().status_code == 200
        url = reverse("pipeline-artists-recovery", kwargs={"uuid": uuid})
        assert self.pipeline.get(url).status_code == 200
        ImportAttempt.objects.create(
            kind="songs", mode="full", run_id=144, task_id="new", attempt=1, state="succeeded", data_applied=True
        )
        assert self.pipeline.get(url).status_code == 409

    @patch("grow.view.viewset.mixin.BulkImportRunMixin.enqueue_merge")
    def test_recovery_reuses_staging_and_durable_commit_across_requests(self, enqueue_merge):
        source = self._failed_gold()
        uuid = self._resume_artists(source).json()["uuid"]
        assert self._claim().status_code == 200
        fingerprints = reverse("pipeline-gold-fingerprints", kwargs={"uuid": uuid})
        response = self.pipeline.patch(fingerprints, data={"artistsSnapshotSha256": "c" * 64}, format="json")
        assert response.status_code == 204, response.content
        artists = reverse("artist-list") + "import-runs/"
        header = {"HTTP_X_PIPELINE_RUN_REQUEST": uuid}
        declaration = {"expectedParts": {"artists": 1}}
        assert self.pipeline.post(artists, data={}, format="json").status_code == 409
        assert self.pipeline.post(artists, data={}, format="json", **header).status_code == 400
        prepared = self.pipeline.post(artists, data=declaration, format="json", **header)
        assert prepared.status_code == 201, prepared.content
        run_id = prepared.json()["runId"]
        assert self.pipeline.post(artists, data=declaration, format="json", **header).json() == {"runId": run_id}
        assert (
            self.pipeline.post(artists, data={"expectedParts": {"artists": 2}}, format="json", **header).status_code
            == 409
        )
        commit = f"{artists}{run_id}/commit/"
        assert self.pipeline.post(commit, **header).status_code == 400
        body = {"data": gzip.compress(b""), "content_type": "application/x-ndjson", "HTTP_CONTENT_ENCODING": "gzip"}
        part = f"{artists}{run_id}/parts/0/"
        assert self.api_client.put(part, **body, **header).status_code == 403
        assert self.pipeline.put(part, **body).status_code == 409
        assert self.pipeline.put(f"{artists}{run_id}/parts/1/", **body, **header).status_code == 400
        PipelineRunRequest.objects.filter(uuid=uuid).update(cancel_requested_on=timezone.now())
        assert self.pipeline.put(part, **body, **header).status_code == 409
        PipelineRunRequest.objects.filter(uuid=uuid).update(cancel_requested_on=None)
        with patch("grow.artist.bulk_import.part_loader.copy_part", return_value=0):
            response = self.pipeline.put(part, **body, **header)
        assert response.status_code == 200, response.content
        first = self.pipeline.post(commit, **header)
        assert first.status_code == 202, first.content
        repeated = self.pipeline.post(commit, **header)
        assert repeated.status_code == 202, repeated.content
        assert repeated.json() == first.json()
        enqueue_merge.assert_called_once()
        attempt = ImportAttempt.objects.get(run_id=run_id)

        assert self._patch(uuid, {"status": "failed"}).status_code == 200
        next_uuid = self._resume_artists(source).json()["uuid"]
        assert self._claim().status_code == 200
        url = reverse("pipeline-artists-recovery", kwargs={"uuid": next_uuid})
        state = self.pipeline.get(url).json()
        assert (state["artistsRunId"], state["artistsTaskId"]) == (run_id, attempt.task_id)
        assert state["artistsApplied"] is False
        assert self._latest().json()["activeImport"]["taskId"] == attempt.task_id
        assert self._patch(next_uuid, {"status": "succeeded"}).status_code == 409
        ImportReceipt.objects.create(run_id=run_id, result={})
        ImportAttempt.objects.filter(pk=attempt.pk).update(state="failed")
        state = self.pipeline.get(url).json()
        assert state["artistsApplied"] is True
        assert state["snapshotsFinalized"] is False
        assert (
            self.api_client.patch(
                reverse("pipeline-run", kwargs={"uuid": next_uuid}), data={"status": "succeeded"}, format="json"
            ).status_code
            == 403
        )
        assert self._patch(next_uuid, {"status": "succeeded"}).status_code == 200
        assert self._resume_artists(source).status_code == 409

    def test_request_claim_progress_succeed(self):
        requested = self._request()
        assert (requested["kind"], requested["status"]) == ("curation", "queued")
        assert (requested["trigger"], requested["requestedBy"]) == ("manual", ADMIN_EMAIL)
        assert set(requested) == {
            "uuid",
            "kind",
            "trigger",
            "requestedBy",
            "status",
            "stage",
            "stageCurrent",
            "stageTotal",
            "stepTelemetry",
            "error",
            "requestedOn",
            "startedOn",
            "heartbeatOn",
            "finishedOn",
            "cancelRequested",
        }

        claimed = self._claim().json()
        assert claimed["uuid"] == requested["uuid"]
        assert (claimed["trigger"], claimed["requestedBy"]) == ("manual", ADMIN_EMAIL)
        assert claimed["status"] == "running"
        assert claimed["startedOn"] is not None
        assert claimed["heartbeatOn"] == claimed["startedOn"]
        assert self._claim().status_code == status.HTTP_204_NO_CONTENT

        progress = self._patch(requested["uuid"], {"stage": "uploading_songs", "stageCurrent": 2, "stageTotal": 9})
        assert progress.status_code == status.HTTP_200_OK, progress.content
        assert progress.json()["stageCurrent"] == 2
        assert progress.json()["heartbeatOn"] > claimed["heartbeatOn"]
        next_stage = self._patch(requested["uuid"], {"stage": "merging_songs"}).json()
        assert (next_stage["stage"], next_stage["stageCurrent"], next_stage["stageTotal"]) == (
            "merging_songs",
            None,
            None,
        )

        done = self._patch(requested["uuid"], {"status": "succeeded"}).json()
        assert (done["status"], done["trigger"], done["requestedBy"]) == ("succeeded", "manual", ADMIN_EMAIL)
        assert done["finishedOn"] is not None
        assert self._patch(requested["uuid"], {"stage": "merging_songs"}).status_code == status.HTTP_409_CONFLICT

        assert self._latest_run() == done
        assert self.api_client.get(path=reverse("pipeline-runs-latest")).json() == {
            **done,
            "activeImport": None,
            "typicalStageSeconds": None,
        }

    def test_background_geohistory_failure_replaces_foreground_stage(self):
        uuid = self._request("full")["uuid"]
        assert self._claim().status_code == status.HTTP_200_OK
        assert self._patch(uuid, {"stage": "building_songs"}).status_code == status.HTTP_200_OK

        error = "source=overpass snapshot=2026-11-20T16:00:00Z relation=123 HTTP 403"
        failed = self._patch(uuid, {"status": "failed", "stage": "ingesting_geohistory", "error": error})
        assert failed.status_code == status.HTTP_200_OK, failed.content
        result = failed.json()
        assert (result["status"], result["stage"], result["error"]) == ("failed", "ingesting_geohistory", error)
        assert result["finishedOn"] is not None
        assert self._latest_run() == result

    def test_full_step_telemetry_survives_independent_progress_and_terminal_updates(self):
        uuid = self._request("full")["uuid"]
        assert self._claim().json()["stepTelemetry"] is None
        wikidata = {
            "stage": "ingesting_wikidata",
            "startedAt": "2026-11-20T12:00:00Z",
            "finishedAt": None,
            "state": "running",
        }
        foreground = {**wikidata, "stage": "ingesting_musicbrainz"}
        retry = {"attempt": 3, "reason": "http", "httpStatus": 503}
        started = self._patch(
            uuid, {"stepTelemetry": {"variant": "bronze_only", "wikidata": [wikidata], "wikidataRetry": retry}}
        )
        assert started.status_code == status.HTTP_200_OK, started.content
        update = {"stage": "ingesting_musicbrainz", "stepTelemetry": {"foreground": [foreground]}}
        for payload in (update, update, {}):
            beat = self._patch(uuid, payload)
            assert beat.status_code == status.HTTP_200_OK, beat.content
            assert beat.json()["stage"] == "ingesting_musicbrainz"
            assert beat.json()["stepTelemetry"] == {
                "variant": "bronze_only",
                "wikidata": [wikidata],
                "foreground": [foreground],
                "wikidataRetry": retry,
            }

        finished = {**wikidata, "state": "succeeded", "finishedAt": "2026-11-20T12:05:00Z"}
        finished_foreground = {**finished, "stage": foreground["stage"]}
        done = self._patch(
            uuid,
            {
                "status": "succeeded",
                "stepTelemetry": {"wikidata": [finished], "foreground": [finished_foreground], "wikidataRetry": None},
            },
        )
        assert done.status_code == status.HTTP_200_OK, done.content
        assert done.json()["stepTelemetry"]["wikidata"] == [finished]
        assert done.json()["stepTelemetry"]["wikidataRetry"] is None
        assert self._latest_run() == done.json()
        assert self.api_client.get(reverse("pipeline-runs")).json()["results"][0] == {
            **done.json(),
            "artistsRecovery": None,
        }

    def test_importing_graph_stage_follows_importing_tree(self):
        uuid = self._request("full")["uuid"]
        assert self._claim().status_code == status.HTTP_200_OK
        tree = {
            "stage": "importing_tree",
            "startedAt": "2026-11-20T12:00:00Z",
            "finishedAt": None,
            "state": "running",
        }
        running = self._patch(
            uuid, {"stage": "importing_tree", "stepTelemetry": {"variant": "bronze_only", "foreground": [tree]}}
        )
        assert running.status_code == status.HTTP_200_OK, running.content

        tree_done = {**tree, "state": "succeeded", "finishedAt": "2026-11-20T12:04:00Z"}
        graph = {**tree, "stage": "importing_graph", "startedAt": "2026-11-20T12:04:00Z"}
        graph_running = self._patch(
            uuid, {"stage": "importing_graph", "stepTelemetry": {"foreground": [tree_done, graph]}}
        )
        assert graph_running.status_code == status.HTTP_200_OK, graph_running.content
        assert graph_running.json()["stage"] == "importing_graph"
        assert graph_running.json()["stepTelemetry"]["foreground"] == [tree_done, graph]

    def test_rejects_invalid_step_telemetry(self):
        uuid = self._request("full")["uuid"]
        self._claim()
        step = {
            "stage": "ingesting_wikidata",
            "startedAt": "2026-11-20T12:00:00Z",
            "finishedAt": None,
            "state": "running",
        }
        for patch in (
            {"wikidata": [step]},
            {"variant": "bronze_only", "wikidata": [step, step]},
            {"variant": "bronze_only", "wikidata": [step, {**step, "stage": "ingesting_geohistory"}]},
            {"variant": "bronze_only", "foreground": [{**step, "stage": "unknown"}]},
            {"variant": "bronze_only", "wikidataRetry": {"attempt": 3, "reason": "timeout", "httpStatus": 503}},
        ):
            response = self._patch(uuid, {"stepTelemetry": patch})
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert self._latest().json()["stepTelemetry"] is None

    def test_rejects_step_telemetry_that_drops_or_rewrites_earlier_steps(self):
        uuid = self._request("full")["uuid"]
        self._claim()
        done = {
            "stage": "ingesting_wikidata",
            "startedAt": "2026-11-20T12:00:00Z",
            "finishedAt": "2026-11-20T12:01:00Z",
            "state": "succeeded",
        }
        second = {**done, "stage": "ingesting_geohistory", "startedAt": "2026-11-20T12:02:00Z", "finishedAt": None}
        second["state"] = "running"
        ok = self._patch(uuid, {"stepTelemetry": {"variant": "bronze_only", "wikidata": [done, second]}})
        assert ok.status_code == status.HTTP_200_OK, ok.content
        for wikidata in (
            [done],
            [{**done, "finishedAt": "2026-11-20T12:01:30Z"}, second],
            [done, {**second, "startedAt": "2026-11-20T12:03:00Z"}],
        ):
            response = self._patch(uuid, {"stepTelemetry": {"wikidata": wikidata}})
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        finished = {**second, "state": "succeeded", "finishedAt": "2026-11-20T12:04:00Z"}
        assert self._patch(uuid, {"stepTelemetry": {"wikidata": [done, finished]}}).status_code == status.HTTP_200_OK

    def test_step_telemetry_is_rejected_on_a_curation_run(self):
        uuid = self._request("curation")["uuid"]
        self._claim()

        response = self._patch(uuid, {"stepTelemetry": {"variant": "bronze_only"}})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_empty_patch_is_a_heartbeat(self):
        uuid = self._request("full")["uuid"]
        self._claim()
        self._go_silent(uuid, 10)

        beat = self._patch(uuid, {})

        assert beat.status_code == status.HTTP_200_OK, beat.content
        assert (beat.json()["status"], beat.json()["cancelRequested"]) == ("running", False)
        assert PipelineRunRequest.objects.get(uuid=uuid).heartbeat_on > timezone.now() - timedelta(minutes=1)

    def test_failure_records_error(self):
        uuid = self._request()["uuid"]
        self._claim()

        failed = self._patch(uuid, {"status": "failed", "error": "gold stage crashed"}).json()

        assert (failed["status"], failed["error"]) == ("failed", "gold stage crashed")
        assert failed["finishedOn"] is not None

    def test_second_request_while_active_conflicts_across_kinds(self):
        self._request()
        assert self._post("full").status_code == status.HTTP_409_CONFLICT
        self._claim()
        assert self._post("curation").status_code == status.HTTP_409_CONFLICT

    def test_single_active_constraint(self):
        PipelineRunRequest.objects.create(kind="full", status=PipelineRunRequest.Status.RUNNING)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PipelineRunRequest.objects.create(kind="curation")
        PipelineRunRequest.objects.create(kind="full", status=PipelineRunRequest.Status.FAILED)

    def test_curation_with_nothing_pending_rejected(self):
        response = self._post("curation")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not PipelineRunRequest.objects.exists()

    def test_kind_required(self):
        assert self._post("nope").status_code == status.HTTP_400_BAD_REQUEST
        response = self.api_client.post(path=reverse("pipeline-runs"), data={}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_curation_superseded_when_nightly_applied_everything(self):
        uuid = self._request()["uuid"]
        self._nightly_applies_everything()

        claimed = self._claim().json()

        assert (claimed["uuid"], claimed["status"]) == (uuid, "superseded")
        assert claimed["startedOn"] is None
        assert claimed["finishedOn"] is not None
        assert self._patch(uuid, {"status": "succeeded"}).status_code == status.HTTP_409_CONFLICT

    def test_full_never_superseded(self):
        uuid = self._request("full")["uuid"]

        claimed = self._claim().json()

        assert (claimed["uuid"], claimed["kind"], claimed["status"]) == (uuid, "full", "running")

    def test_sync_requested_with_nothing_pending_and_claimed_normally(self):
        uuid = self._request("sync")["uuid"]

        claimed = self._claim().json()

        assert (claimed["uuid"], claimed["kind"], claimed["status"]) == (uuid, "sync", "running")
        for stage in (
            "ingesting_discogs",
            "building_gold",
            "uploading_artists",
            "merging_artists",
            "uploading_region_map",
            "merging_region_map",
        ):
            response = self._patch(uuid, {"stage": stage})
            assert response.status_code == status.HTTP_200_OK, response.content
            assert response.json()["stage"] == stage

    def test_pipeline_key_sync_rejected(self):
        response = self.pipeline.post(path=reverse("pipeline-runs"), data={"kind": "sync"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not PipelineRunRequest.objects.exists()

    def test_cancel_queued(self):
        uuid = self._request("full")["uuid"]

        cancelled = self._cancel(uuid)

        assert cancelled.status_code == status.HTTP_200_OK, cancelled.content
        assert (cancelled.json()["status"], cancelled.json()["cancelRequested"]) == ("cancelled", True)
        assert cancelled.json()["finishedOn"] is not None
        assert self._claim().status_code == status.HTTP_204_NO_CONTENT
        assert self._cancel(uuid).status_code == status.HTTP_409_CONFLICT
        self._request("full")

    def test_cancel_running(self):
        uuid = self._request("full")["uuid"]
        self._claim()

        flagged = self._cancel(uuid).json()
        assert (flagged["status"], flagged["cancelRequested"]) == ("running", True)
        assert self._cancel(uuid).status_code == status.HTTP_200_OK
        assert self._patch(uuid, {"stage": "ingesting_wikidata"}).json()["cancelRequested"] is True

        cancelled = self._patch(uuid, {"status": "cancelled"}).json()
        assert cancelled["status"] == "cancelled"
        assert cancelled["finishedOn"] is not None
        self._request("full")

    def test_patch_rejects_invalid_values(self):
        uuid = self._request()["uuid"]
        self._claim()

        assert self._patch(uuid, {"status": "queued"}).status_code == status.HTTP_400_BAD_REQUEST
        assert self._patch(uuid, {"status": "expired"}).status_code == status.HTTP_400_BAD_REQUEST
        assert self._patch(uuid, {"stage": "nope"}).status_code == status.HTTP_400_BAD_REQUEST
        assert self._patch(uuid, {"stageCurrent": -1}).status_code == status.HTTP_400_BAD_REQUEST

    def test_silent_running_request_expires(self):
        timeout = settings.PIPELINE_RUN_HEARTBEAT_TIMEOUT_MINUTES
        uuid = self._request("full")["uuid"]
        self._claim()
        self._go_silent(uuid, timeout - 1)
        assert self._latest().json()["status"] == "running"

        self._go_silent(uuid, timeout + 1)

        expired = self._latest().json()
        assert expired["status"] == "expired"
        assert expired["finishedOn"] is not None
        assert self._patch(uuid, {}).status_code == status.HTTP_409_CONFLICT
        assert self._cancel(uuid).status_code == status.HTTP_409_CONFLICT
        self._request("full")

    def test_patch_on_silent_request_expires_it(self):
        uuid = self._request("full")["uuid"]
        self._claim()
        self._go_silent(uuid, settings.PIPELINE_RUN_HEARTBEAT_TIMEOUT_MINUTES + 1)

        assert self._patch(uuid, {"status": "succeeded"}).status_code == status.HTTP_409_CONFLICT
        assert PipelineRunRequest.objects.get(uuid=uuid).status == "expired"

    def test_create_and_claim_expire_dead_run(self):
        dead = self._request("full")["uuid"]
        self._claim()
        self._go_silent(dead, settings.PIPELINE_RUN_HEARTBEAT_TIMEOUT_MINUTES + 1)

        uuid = self._request("full")["uuid"]

        assert PipelineRunRequest.objects.get(uuid=dead).status == "expired"
        assert self._claim().json()["uuid"] == uuid

    def test_queued_request_never_expires(self):
        uuid = self._request("full")["uuid"]
        PipelineRunRequest.objects.filter(uuid=uuid).update(requested_on=timezone.now() - timedelta(days=1))

        assert self._claim().json()["status"] == "running"

    def test_latest_empty(self):
        assert self._latest().status_code == status.HTTP_204_NO_CONTENT

    def test_unknown_uuid(self):
        unknown = "00000000-0000-0000-0000-000000000000"
        assert self._patch(unknown, {}).status_code == status.HTTP_404_NOT_FOUND
        assert self._cancel(unknown).status_code == status.HTTP_404_NOT_FOUND

    def test_permissions(self):
        uuid = self._request("full")["uuid"]
        anonymous = APIClient()
        assert anonymous.post(path=reverse("pipeline-runs")).status_code == status.HTTP_401_UNAUTHORIZED
        assert anonymous.get(path=reverse("pipeline-runs-latest")).status_code == status.HTTP_401_UNAUTHORIZED
        assert anonymous.post(path=reverse("pipeline-runs-claim")).status_code == status.HTTP_401_UNAUTHORIZED
        assert self._cancel(uuid, anonymous).status_code == status.HTTP_401_UNAUTHORIZED
        run_url = reverse("pipeline-run", kwargs={"uuid": uuid})
        assert anonymous.patch(path=run_url, data={}, format="json").status_code == status.HTTP_401_UNAUTHORIZED
        assert anonymous.get(path=reverse("pipeline-runs")).status_code == status.HTTP_401_UNAUTHORIZED
        assert self.pipeline.get(path=reverse("pipeline-runs")).status_code == status.HTTP_403_FORBIDDEN
        viewer = APIClient()
        viewer.force_authenticate(user=self.admin, token=Principal(role="viewer", email=None, sub=None))
        assert viewer.get(path=reverse("pipeline-runs")).status_code == status.HTTP_403_FORBIDDEN
        assert viewer.post(path=reverse("pipeline-runs"), data={"kind": "full"}).status_code == 403
        assert self._cancel(uuid, self.pipeline).status_code == status.HTTP_403_FORBIDDEN

    def test_pipeline_key_requests_scheduled_full_run(self):
        response = self.pipeline.post(path=reverse("pipeline-runs"), data={"kind": "full"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert (response.json()["trigger"], response.json()["requestedBy"]) == ("scheduled", None)
        run = PipelineRunRequest.objects.get()
        assert (run.trigger, run.requested_by) == ("scheduled", None)
        claimed = self._claim().json()
        assert (claimed["trigger"], claimed["requestedBy"]) == ("scheduled", None)
        done = self._patch(claimed["uuid"], {"status": "succeeded"}).json()
        assert (done["trigger"], done["requestedBy"]) == ("scheduled", None)
        assert self._latest_run() == done

    def test_pipeline_key_curation_rejected(self):
        self._edit()

        response = self.pipeline.post(path=reverse("pipeline-runs"), data={"kind": "curation"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not PipelineRunRequest.objects.exists()

    def test_admin_request_records_requester(self):
        self._request("full")

        run = PipelineRunRequest.objects.get()
        assert (run.trigger, run.requested_by) == ("manual", self.admin)

    def test_list_newest_first_and_paginated(self):
        uuids = []
        for _ in range(3):
            uuid = self._request("full")["uuid"]
            self._cancel(uuid)
            uuids.append(uuid)

        first = self.api_client.get(path=reverse("pipeline-runs"), data={"page_size": 2}).json()
        second = self.api_client.get(path=reverse("pipeline-runs"), data={"page_size": 2, "page": 2}).json()

        assert [r["uuid"] for r in first["results"]] == uuids[:0:-1]
        assert [r["uuid"] for r in second["results"]] == uuids[:1]
        assert (first["overallTotal"], first["totalPages"], first["pageSize"]) == (3, 2, 2)
        assert first["results"][0]["requestedBy"] == ADMIN_EMAIL

    def test_list_expires_dead_run(self):
        uuid = self._request("full")["uuid"]
        self._claim()
        self._go_silent(uuid, settings.PIPELINE_RUN_HEARTBEAT_TIMEOUT_MINUTES + 1)

        listed = self.api_client.get(path=reverse("pipeline-runs")).json()

        assert listed["results"][0]["status"] == "expired"
