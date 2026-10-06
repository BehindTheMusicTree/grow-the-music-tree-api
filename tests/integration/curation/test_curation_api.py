from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework import status

from grow.curation.lists import CURATION_LISTS
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.integration.permission.test_google_id_token_auth import VERIFY, VIEWER_CLAIMS
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

    def test_lists_then_entry_counts(self):
        self._create(ITEM)

        lists = {lst["name"]: lst for lst in self.api_client.get(path=reverse("curation-lists")).json()}

        assert lists["theme_genres"]["count"] == CurationEntry.objects.filter(list_name="theme_genres").count()
        assert lists["theme_genres"]["count"] > 0

    def test_search_then_matches_key_values_reason_and_genre_name(self):
        self.model_fixture_factory.create_genre("Shoegaze", wikidata_id="Q999999993")
        self._create(ITEM)
        self._create({**ITEM, "item_id": "Q999999992", "item_label": "drone", "reason": "noise wall"})
        self._create({**ITEM, "item_id": "Q999999993", "item_label": "x"})

        def keys(q: str) -> list[str]:
            response = self.api_client.get(path=self._entries_url(), data={"q": q})
            return sorted(e["row"]["item_id"] for e in response.json()["results"])

        assert keys("Q999999991") == ["Q999999991"]
        assert keys("DRONE") == ["Q999999992"]
        assert keys("wall") == ["Q999999992"]
        assert keys("shoegaze") == ["Q999999993"]

    def test_ordering_then_most_recent_first(self):
        self._create({**ITEM, "item_id": "Q999999992"})
        self._create(ITEM)

        response = self.api_client.get(path=self._entries_url(), data={"ordering": "-updated_on"})

        assert [e["row"]["item_id"] for e in response.json()["results"][:2]] == ["Q999999991", "Q999999992"]

    def test_unknown_ordering_then_400(self):
        response = self.api_client.get(path=self._entries_url(), data={"ordering": "reason"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_entries_then_labels_for_every_item_id_column(self):
        self.model_fixture_factory.create_genre("Rock", wikidata_id="Q999999991")
        self.model_fixture_factory.create_genre("Blues", wikidata_id="Q999999992")
        self._create({**ITEM, "parent_item_id": "Q999999992", "exclude_other_parents": False}, "main_parent")

        response = self.api_client.get(path=self._entries_url("main_parent"), data={"q": "Q99999999"})

        labels = response.json()["labels"]

        assert labels == {"Q999999991": "Rock", "Q999999992": "Blues"}

    def test_rules_then_entries_referencing_item_by_key_value_and_composite_key(self):
        self.model_fixture_factory.create_genre("Rock", wikidata_id="Q999999991")
        self._create(ITEM)
        self._create(
            {**ITEM, "item_id": "Q999999992", "parent_item_id": "Q999999991", "exclude_other_parents": False},
            "main_parent",
        )
        row = {"item_id": "Q999999993", "item_label": "x", "parent_id": "Q999999991", "parent_label": "Rock"}
        self._create({**row, "reason": "r"}, "regional_secondary_parents")
        self._create({**ITEM, "item_id": "Q9999999910"})

        response = self.api_client.get(path=reverse("curation-rules"), data={"item_id": "Q999999991"})

        assert response.status_code == status.HTTP_200_OK
        assert [(r["listName"], r["row"]["item_id"]) for r in response.json()["results"]] == [
            ("main_parent", "Q999999992"),
            ("regional_secondary_parents", "Q999999993"),
            ("theme_genres", "Q999999991"),
        ]
        assert response.json()["labels"] == {"Q999999991": "Rock"}

    def test_rules_with_invalid_item_id_then_400(self):
        response = self.api_client.get(path=reverse("curation-rules"), data={"item_id": "rock"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

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

    def test_local_item_id_then_accepted(self):
        assert self._create({**ITEM, "item_id": "LOCAL:my-genre"}).status_code == status.HTTP_201_CREATED

    def test_tab_in_key_column_then_400(self):
        row = {"root_genre_name": "rock\tx", "pop_child_genre_name": "pop", "reason": "r"}

        assert self._create(row, "canonical_genre_pop_side").status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_key_to_existing_then_400(self):
        self._create(ITEM)
        other = self._create({**ITEM, "item_id": "Q999999992"}).json()["uuid"]

        response = self.api_client.patch(self._entry_url(other), {"row": {"item_id": ITEM["item_id"]}}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_same_key_in_exclusive_list_then_200(self):
        uuid = self._create(ITEM).json()["uuid"]

        response = self.api_client.patch(self._entry_url(uuid), {"row": {"item_id": ITEM["item_id"]}}, format="json")

        assert response.status_code == status.HTTP_200_OK

    def test_non_admin_token_then_403(self):
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            response = self.api_client.get(path=reverse("curation-lists"))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_dict_body_then_400(self):
        uuid = self._create(ITEM).json()["uuid"]

        post = self.api_client.post(path=self._entries_url(), data=[ITEM], format="json")
        patch_ = self.api_client.patch(self._entry_url(uuid), [ITEM], format="json")

        assert (post.status_code, patch_.status_code) == (status.HTTP_400_BAD_REQUEST, status.HTTP_400_BAD_REQUEST)

    def test_item_id_with_trailing_newline_or_non_ascii_digit_then_400(self):
        for item_id in ("Q123\n", "Q\u0661\u0662\u0663"):
            assert self._create({**ITEM, "item_id": item_id}).status_code == status.HTTP_400_BAD_REQUEST, item_id

    def test_key_longer_than_column_then_400(self):
        response = self._create({**ITEM, "item_id": "LOCAL:" + "a" * 600})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "512" in str(response.json())

    def test_genre_precedence_then_created(self):
        row = {"musicbrainz_genre_name": "test ska", "over_musicbrainz_genre_name": "test reggae", "reason": "r"}

        response = self._create(row, "genre_precedence")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["row"] == row

    def test_genre_precedence_invalid_names_then_400(self):
        for winner, over in (("Ska", "reggae"), ("ska", "Reggae"), ("ska", "ska"), ("", "reggae")):
            row = {"musicbrainz_genre_name": winner, "over_musicbrainz_genre_name": over, "reason": "r"}

            assert self._create(row, "genre_precedence").status_code == status.HTTP_400_BAD_REQUEST, row
