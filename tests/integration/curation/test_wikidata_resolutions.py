from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.integration.permission.test_google_id_token_auth import VERIFY, VIEWER_CLAIMS
from tests.utils.AppTestCase import AppTestCase

OLD, NEW = "Q999999900", "Q999999901"


def _remap(list_name: str, key: str, column: str = "item_id", old: str = OLD, new: str = NEW) -> dict:
    return {"list": list_name, "key": key, "column": column, "from": old, "to": new}


def _entry(list_name: str, key: str, **values) -> CurationEntry:
    return CurationEntry.objects.create(user=None, list_name=list_name, key=key, values=values, reason="r")


class TestWikidataResolutions(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

    def _report(self, remaps: list[dict], review: list[dict] | None = None):
        return self.pipeline.post(
            path=reverse("curation-wikidata-resolutions"),
            data={"remaps": remaps, "review": review or []},
            format="json",
        )

    def _review(self) -> list[dict]:
        response = self.api_client.get(path=reverse("curation-review"))
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_remap_key_then_rewritten_with_pipeline_history(self):
        entry = _entry("technique_genres", OLD, item_label="x")

        response = self._report([_remap("technique_genres", OLD)])

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"remappedCount": 1, "reviewCount": 0}
        entry.refresh_from_db()
        assert entry.key == NEW
        [history] = HistoryEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(CurationEntry), action=HistoryAction.UPDATED
        )
        assert history.content_uuid == entry.uuid
        assert history.actor is None
        assert OLD in history.old_value and NEW in history.new_value

    def test_remap_value_and_composite_key_then_rewritten(self):
        main = _entry("main_parent", "Q999999001", item_label="x", parent_item_id=OLD, exclude_other_parents=False)
        edge = _entry("regional_secondary_parents", "Q999999002\tQ999999003", item_label="a", parent_label="b")

        response = self._report(
            [
                _remap("main_parent", "Q999999001", "parent_item_id"),
                _remap("regional_secondary_parents", "Q999999002\tQ999999003", "item_id", "Q999999002", "Q999999020"),
                _remap("regional_secondary_parents", "Q999999002\tQ999999003", "parent_id", "Q999999003", "Q999999030"),
            ]
        )

        assert response.json()["remappedCount"] == 3
        main.refresh_from_db()
        edge.refresh_from_db()
        assert main.values["parent_item_id"] == NEW
        assert edge.key == "Q999999020\tQ999999030"

    def test_remap_onto_existing_or_exclusive_entry_then_review_item(self):
        _entry("technique_genres", OLD, item_label="x")
        _entry("technique_genres", NEW, item_label="y")
        _entry("theme_genres", "Q999999005", item_label="z")
        _entry("out_of_scope_genres", "Q999999006", item_label="w")

        response = self._report(
            [_remap("technique_genres", OLD), _remap("theme_genres", "Q999999005", old="Q999999005", new="Q999999006")]
        )

        assert response.json() == {"remappedCount": 0, "reviewCount": 2}
        assert CurationEntry.objects.filter(key=OLD).exists()
        assert [(i["key"], i["itemId"], i["reason"], i["target"]) for i in self._review()] == [
            (OLD, OLD, "redirect_conflict", NEW),
            ("Q999999005", "Q999999005", "redirect_conflict", "Q999999006"),
        ]

    def test_unknown_entry_or_already_fixed_then_skipped(self):
        _entry("technique_genres", "Q999999007", item_label="x")

        response = self._report(
            [_remap("technique_genres", OLD), _remap("technique_genres", "Q999999007", old="Q999999008")]
        )

        assert response.json() == {"remappedCount": 0, "reviewCount": 0}
        assert not HistoryEntry.objects.filter(action=HistoryAction.UPDATED).exists()

    def test_report_then_replaces_previous_review_items(self):
        missing = {
            "list": "theme_genres",
            "key": "Q999999009",
            "column": "item_id",
            "itemId": "Q999999009",
            "reason": "missing",
        }
        self._report([], [missing])
        self._report([], [{**missing, "key": "Q999999010", "itemId": "Q999999010", "reason": "not_in_tree"}])

        [item] = self._review()
        assert item["key"] == "Q999999010"
        assert item["reason"] == "not_in_tree"
        assert item["target"] is None
        assert "reportedOn" in item

    def test_invalid_report_then_400(self):
        for remap in [
            _remap("nope", OLD),
            _remap("technique_genres", OLD, new="bad"),
            _remap("technique_genres", OLD, column="parent_item_id"),
        ]:
            assert self._report([remap]).status_code == status.HTTP_400_BAD_REQUEST
        assert CurationReviewItem.objects.count() == 0

    def test_auth(self):
        url = reverse("curation-wikidata-resolutions")
        assert APIClient().post(url, {"remaps": [], "review": []}, format="json").status_code == 401
        assert self.pipeline.get(reverse("curation-review")).status_code == status.HTTP_403_FORBIDDEN
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            assert self.api_client.post(path=url, data={"remaps": [], "review": []}).status_code == 403
            assert self.api_client.get(path=reverse("curation-review")).status_code == 403
