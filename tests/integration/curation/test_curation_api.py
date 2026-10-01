from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework import status

from grow.curation.lists import CURATION_LISTS
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.utils.AppTestCase import AppTestCase

ITEM = {"item_id": "Q999999991", "item_label": "test genre", "reason": "testing"}


class TestCase(AppTestCase):
    def _entries_url(self, list_name: str = "theme_genres") -> str:
        return reverse("curation-entries", kwargs={"list_name": list_name})

    def _entry_url(self, uuid, list_name: str = "theme_genres") -> str:
        return reverse("curation-entry", kwargs={"list_name": list_name, "uuid": uuid})

    def _create(self, row: dict, list_name: str = "theme_genres"):
        return self.api_client.post(path=self._entries_url(list_name), data={"row": row})

    def _history(self, uuid) -> list[HistoryEntry]:
        return list(
            HistoryEntry.objects.filter(
                content_type=ContentType.objects.get_for_model(CurationEntry), content_uuid=uuid
            ).order_by("created_on")
        )

    def test_lists_then_registry(self):
        response = self.api_client.get(path=reverse("curation-lists"))

        assert response.status_code == status.HTTP_200_OK
        lists = {lst["name"]: lst for lst in response.json()}
        assert set(lists) == set(CURATION_LISTS)
        assert lists["canonical_genre_pop_side"]["keyColumns"] == ["root_genre_name", "pop_child_genre_name"]

    def test_create_then_row_snake_case_and_history(self):
        response = self._create(ITEM)

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["row"] == ITEM
        assert "createdOn" in body
        [entry] = self._history(body["uuid"])
        assert entry.action == HistoryAction.CREATED
        assert entry.actor == self.admin

    def test_list_entries_then_paginated(self):
        self._create(ITEM, "indigenous_to_exclusions")

        response = self.api_client.get(path=self._entries_url("indigenous_to_exclusions"))

        assert response.status_code == status.HTTP_200_OK
        assert ITEM in [e["row"] for e in response.json()["results"]]

    def test_patch_then_merged_and_history(self):
        uuid = self._create(ITEM).json()["uuid"]

        response = self.api_client.patch(self._entry_url(uuid), {"row": {"reason": "changed"}}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["row"] == {**ITEM, "reason": "changed"}
        assert [h.action for h in self._history(uuid)] == [HistoryAction.CREATED, HistoryAction.UPDATED]

    def test_delete_then_gone_and_history(self):
        uuid = self._create(ITEM).json()["uuid"]

        response = self.api_client.delete(self._entry_url(uuid))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not CurationEntry.objects.filter(uuid=uuid).exists()
        assert self._history(uuid)[-1].action == HistoryAction.DELETED

    def test_composite_key_then_split_back(self):
        row = {"root_genre_name": "rock", "pop_child_genre_name": "test pop child", "reason": "r"}

        response = self._create(row, "canonical_genre_pop_side")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["row"] == row
        assert CurationEntry.objects.get(uuid=response.json()["uuid"]).key == "rock\ttest pop child"

    def test_bool_column_then_coerced(self):
        row = {**ITEM, "parent_item_id": "Q11399", "exclude_other_parents": "true"}

        response = self._create(row, "main_parent")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["row"]["exclude_other_parents"] is True

    def test_invalid_row_then_400(self):
        for row in (
            {**ITEM, "item_id": "not-a-qid"},
            {**ITEM, "extra": "x"},
            {"item_id": "Q999999991"},
        ):
            assert self._create(row).status_code == status.HTTP_400_BAD_REQUEST, row

    def test_duplicate_key_then_400(self):
        self._create(ITEM)

        assert self._create(ITEM).status_code == status.HTTP_400_BAD_REQUEST

    def test_exclusive_lists_then_400(self):
        self._create(ITEM, "theme_genres")

        response = self._create(ITEM, "technique_genres")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "theme_genres" in str(response.json())

    def test_non_exclusive_lists_then_both_allowed(self):
        self._create(ITEM, "theme_genres")

        assert self._create(ITEM, "indigenous_to_exclusions").status_code == 201

    def test_unknown_list_then_404(self):
        assert self.api_client.get(path=self._entries_url("nope")).status_code == status.HTTP_404_NOT_FOUND

    def test_anonymous_then_401(self):
        self.api_client.credentials()

        assert self.api_client.get(path=reverse("curation-lists")).status_code == status.HTTP_401_UNAUTHORIZED
        assert self.api_client.get(path=reverse("curation-export")).status_code == status.HTTP_401_UNAUTHORIZED

    def test_pipeline_key_then_export_only(self):
        self.api_client.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

        assert self.api_client.get(path=reverse("curation-export")).status_code == status.HTTP_200_OK
        assert self.api_client.get(path=self._entries_url()).status_code == status.HTTP_403_FORBIDDEN
        assert self._create(ITEM).status_code == status.HTTP_403_FORBIDDEN

    def test_export_then_csv_rows_snake_case(self):
        self._create({**ITEM, "parent_item_id": "Q11399", "exclude_other_parents": False}, "main_parent")

        export = self.api_client.get(path=reverse("curation-export")).json()

        assert set(export) == set(CURATION_LISTS)
        row = next(r for r in export["main_parent"] if r["item_id"] == ITEM["item_id"])
        assert list(row) == list(CURATION_LISTS["main_parent"].columns)
        assert row["exclude_other_parents"] == ""
