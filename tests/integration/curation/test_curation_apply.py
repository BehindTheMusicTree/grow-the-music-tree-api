from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.curation.CurationApplyRequest import CurationApplyRequest
from tests.utils.AppTestCase import AppTestCase

ITEM = {"item_id": "Q999999991", "item_label": "test genre", "reason": "testing"}
TREE = {
    Fields.TREE_NAME: "canonical",
    Fields.TREE: [{Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}],
}


class TestCurationApply(AppTestCase):
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

    def _request(self) -> dict:
        response = self.api_client.post(path=reverse("curation-apply"))
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.json()

    def _claim(self):
        return self.pipeline.post(path=reverse("curation-apply-claim"))

    def _patch(self, uuid: str, data: dict):
        return self.pipeline.patch(
            path=reverse("curation-apply-request", kwargs={"uuid": uuid}), data=data, format="json"
        )

    def test_request_claim_progress_succeed(self):
        self._edit()
        requested = self._request()
        assert requested["status"] == "queued"
        assert set(requested) == {
            "uuid",
            "status",
            "stage",
            "stageCurrent",
            "stageTotal",
            "error",
            "requestedOn",
            "startedOn",
            "finishedOn",
        }

        claimed = self._claim().json()
        assert claimed["uuid"] == requested["uuid"]
        assert claimed["status"] == "running"
        assert claimed["startedOn"] is not None
        assert self._claim().status_code == status.HTTP_204_NO_CONTENT

        progress = self._patch(requested["uuid"], {"stage": "uploading_songs", "stageCurrent": 2, "stageTotal": 9})
        assert progress.status_code == status.HTTP_200_OK, progress.content
        assert progress.json()["stageCurrent"] == 2
        next_stage = self._patch(requested["uuid"], {"stage": "merging_songs"}).json()
        assert (next_stage["stage"], next_stage["stageCurrent"], next_stage["stageTotal"]) == (
            "merging_songs",
            None,
            None,
        )

        done = self._patch(requested["uuid"], {"status": "succeeded"}).json()
        assert done["status"] == "succeeded"
        assert done["finishedOn"] is not None
        assert self._patch(requested["uuid"], {"stage": "merging_songs"}).status_code == status.HTTP_409_CONFLICT

        latest = self.pipeline.get(path=reverse("curation-apply-latest"))
        assert latest.json() == done
        assert self.api_client.get(path=reverse("curation-apply-latest")).json() == done

    def test_failure_records_error(self):
        self._edit()
        uuid = self._request()["uuid"]
        self._claim()

        failed = self._patch(uuid, {"status": "failed", "error": "gold stage crashed"}).json()

        assert (failed["status"], failed["error"]) == ("failed", "gold stage crashed")
        assert failed["finishedOn"] is not None

    def test_second_request_while_active_conflicts(self):
        self._edit()
        self._request()
        assert self.api_client.post(path=reverse("curation-apply")).status_code == status.HTTP_409_CONFLICT
        self._claim()
        assert self.api_client.post(path=reverse("curation-apply")).status_code == status.HTTP_409_CONFLICT

    def test_single_active_constraint(self):
        CurationApplyRequest.objects.create(status=CurationApplyRequest.Status.RUNNING)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CurationApplyRequest.objects.create()
        CurationApplyRequest.objects.create(status=CurationApplyRequest.Status.FAILED)

    def test_nothing_pending_rejected(self):
        response = self.api_client.post(path=reverse("curation-apply"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not CurationApplyRequest.objects.exists()

    def test_superseded_when_nightly_applied_everything(self):
        self._edit()
        uuid = self._request()["uuid"]
        self._nightly_applies_everything()

        claimed = self._claim().json()

        assert (claimed["uuid"], claimed["status"]) == (uuid, "superseded")
        assert claimed["startedOn"] is None
        assert claimed["finishedOn"] is not None
        assert self._patch(uuid, {"status": "succeeded"}).status_code == status.HTTP_409_CONFLICT

    def test_latest_empty(self):
        assert self.api_client.get(path=reverse("curation-apply-latest")).status_code == status.HTTP_204_NO_CONTENT

    def test_patch_rejects_invalid_values(self):
        self._edit()
        uuid = self._request()["uuid"]
        self._claim()

        assert self._patch(uuid, {"status": "queued"}).status_code == status.HTTP_400_BAD_REQUEST
        assert self._patch(uuid, {"stage": "nope"}).status_code == status.HTTP_400_BAD_REQUEST
        assert self._patch(uuid, {"stageCurrent": -1}).status_code == status.HTTP_400_BAD_REQUEST

    def test_permissions(self):
        anonymous = APIClient()
        assert anonymous.post(path=reverse("curation-apply")).status_code == status.HTTP_401_UNAUTHORIZED
        assert anonymous.get(path=reverse("curation-apply-latest")).status_code == status.HTTP_401_UNAUTHORIZED
        assert anonymous.post(path=reverse("curation-apply-claim")).status_code == status.HTTP_401_UNAUTHORIZED
        assert self.pipeline.post(path=reverse("curation-apply")).status_code == status.HTTP_403_FORBIDDEN
