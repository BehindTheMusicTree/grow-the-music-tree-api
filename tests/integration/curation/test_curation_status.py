from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.curation.CurationSyncState import CurationSyncState
from tests.utils.AppTestCase import AppTestCase

ITEM = {"item_id": "Q999999991", "item_label": "test genre", "reason": "testing"}
TREE = {
    Fields.TREE_NAME: "canonical",
    Fields.TREE: [{Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}],
}


class TestCurationStatus(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

    def _status(self) -> dict:
        response = self.api_client.get(path=reverse("curation-status"))
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def _edit(self, row: dict) -> None:
        response = self.api_client.post(
            path=reverse("curation-entries", kwargs={"list_name": "theme_genres"}), data={"row": row}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content

    def _pipeline_run(self) -> None:
        assert self.pipeline.get(path=reverse("curation-export")).status_code == status.HTTP_200_OK
        response = self.pipeline.post(path=reverse("genre-list") + "tree/import/", data=TREE, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_edits_pending_until_pipeline_applies_export(self):
        self._edit(ITEM)
        assert self._status() == {"appliedExportOn": None, "pendingCount": 1}

        self._pipeline_run()
        state = CurationSyncState.load()
        assert state.applied_export_on == state.exported_on is not None
        assert self._status()["pendingCount"] == 0

        self._edit({**ITEM, "item_id": "Q999999992"})
        assert self._status()["pendingCount"] == 1

    def test_admin_export_then_not_recorded(self):
        self.api_client.get(path=reverse("curation-export"))

        assert CurationSyncState.load().exported_on is None
