from datetime import datetime, timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.curation.CurationSyncState import CurationSyncState
from tests.utils.AppTestCase import AppTestCase
from tests.utils.curation_export import export_curation

ITEM = {"item_id": "Q999999991", "reason": "testing"}
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

    def _import_tree(self, curation_exported_on: str | None):
        data = TREE if curation_exported_on is None else {**TREE, "curationExportedOn": curation_exported_on}
        return self.pipeline.post(path=reverse("genre-list") + "tree/import/", data=data, format="json")

    def _pipeline_run(self) -> None:
        response = self._import_tree(export_curation(self.pipeline))
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

    def test_export_then_exported_on_recorded(self):
        exported_on = export_curation(self.pipeline)

        assert CurationSyncState.load().exported_on == datetime.fromisoformat(exported_on)

    def test_older_gold_import_then_later_edits_stay_pending(self):
        gold_exported_on = export_curation(self.pipeline)
        self._edit(ITEM)
        export_curation(self.pipeline)

        assert self._import_tree(gold_exported_on).status_code == status.HTTP_201_CREATED

        assert CurationSyncState.load().applied_export_on == datetime.fromisoformat(gold_exported_on)
        assert self._status()["pendingCount"] == 1

    def test_tree_import_without_curation_exported_on_then_400(self):
        export_curation(self.pipeline)

        response = self._import_tree(None)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert CurationSyncState.load().applied_export_on is None

    def test_tree_import_with_unparseable_curation_exported_on_then_400(self):
        export_curation(self.pipeline)

        assert self._import_tree("yesterday").status_code == status.HTTP_400_BAD_REQUEST

    def test_tree_import_later_than_last_export_then_400(self):
        exported_on = datetime.fromisoformat(export_curation(self.pipeline))

        response = self._import_tree((exported_on + timedelta(seconds=1)).isoformat())

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert CurationSyncState.load().applied_export_on is None

    def test_tree_import_before_any_export_then_400(self):
        assert self._import_tree(timezone.now().isoformat()).status_code == status.HTTP_400_BAD_REQUEST
