from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.authentication.Principal import Principal
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from tests.utils.AppApiClient import ADMIN_EMAIL
from tests.utils.AppTestCase import AppTestCase

ITEM = {"item_id": "Q999999991", "item_label": "test genre", "reason": "testing"}
TREE = {
    Fields.TREE_NAME: "canonical",
    Fields.TREE: [{Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}],
}


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
        assert self.pipeline.get(path=reverse("curation-export")).status_code == status.HTTP_200_OK
        response = self.pipeline.post(path=reverse("genre-list") + "tree/import/", data=TREE, format="json")
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

    def _go_silent(self, uuid: str, minutes: int) -> None:
        PipelineRunRequest.objects.filter(uuid=uuid).update(heartbeat_on=timezone.now() - timedelta(minutes=minutes))

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

        assert self._latest().json() == done
        assert self.api_client.get(path=reverse("pipeline-runs-latest")).json() == done

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
        assert self._latest().json() == done

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
