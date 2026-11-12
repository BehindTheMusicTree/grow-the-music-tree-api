import importlib
import json

from django.apps import apps
from django.conf import settings
from django.urls import reverse
from rest_framework import status

from grow.authentication.Principal import Principal
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.history.HistoryEntry import HistoryEntry
from tests.utils.AppTestCase import AppTestCase

ITEM = {"item_id": "Q999999991", "reason": "testing"}
OTHER = {"item_id": "Q999999992", "reason": "testing"}

backfill = importlib.import_module("grow.migrations.0037_curation_history_list_name").add_list_name


class TestCurationHistory(AppTestCase):
    def _history(self, **params) -> list[dict]:
        response = self.api_client.get(path=reverse("curation-history"), data=params)
        assert response.status_code == status.HTTP_200_OK
        return response.json()["results"]

    def _create(self, row: dict, list_name: str = "theme_genres") -> str:
        response = self.api_client.post(
            path=reverse("curation-entries", kwargs={"list_name": list_name}), data={"row": row}
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()["uuid"]

    def test_edits_then_newest_first_with_list_name_snapshots(self):
        uuid = self._create(ITEM)
        url = reverse("curation-entry", kwargs={"list_name": "theme_genres", "uuid": uuid})
        self.api_client.patch(path=url, data={"row": {"reason": "changed"}}, format="json")
        self.api_client.delete(path=url)

        history = self._history(entry=uuid)

        assert [h["action"] for h in history] == ["deleted", "updated", "created"]
        assert {h["entry"] for h in history} == {uuid}
        assert json.loads(history[1]["newValue"]) == {"list_name": "theme_genres", **ITEM, "reason": "changed"}
        assert history[0]["actorPseudo"] is not None

    def test_filter_by_list_and_item(self):
        theme = self._create(ITEM)
        self._create(OTHER, "indigenous_to_exclusions")

        assert [h["entry"] for h in self._history(list="theme_genres")] == [theme]
        assert [h["entry"] for h in self._history(item_id="Q999999991")] == [theme]
        assert self._history(item_id="Q99999999") == []

    def test_curator_key_edit_then_history_actor_is_curation_bot_pseudo(self):
        self.api_client.credentials(HTTP_X_API_KEY=settings.CURATION_API_KEY)
        self._create(ITEM)
        self.api_client.credentials()
        self.api_client.force_authenticate(
            user=self.admin, token=Principal(role="admin", email=self.admin.email, sub=settings.ADMIN_GOOGLE_SUB)
        )

        [entry] = self._history()

        assert entry["actorPseudo"] == "curation-bot"

    def test_pipeline_edit_then_null_actor(self):
        CurationEntry.objects.upsert("theme_genres", ITEM)

        [entry] = self._history()

        assert entry["actorPseudo"] is None

    def test_invalid_filters_then_400(self):
        for params in ({"list": "nope"}, {"entry": "nope"}, {"item_id": "nope"}):
            response = self.api_client.get(path=reverse("curation-history"), data=params)
            assert response.status_code == status.HTTP_400_BAD_REQUEST, params

    def test_backfill_then_list_name_added_to_live_entries_only(self):
        uuid = self._create(ITEM)
        HistoryEntry.objects.filter(content_uuid=uuid).update(new_value=json.dumps(ITEM))

        backfill(apps, None)

        assert json.loads(HistoryEntry.objects.get(content_uuid=uuid).new_value)["list_name"] == "theme_genres"
