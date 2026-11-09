from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
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
        entry = _entry("technique_genres", OLD)

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
        main = GenreEdgeRule.objects.create(
            user=None,
            relation="canonical_parent",
            item_id="Q999999001",
            parent_item_id=OLD,
            exclude_other_parents=False,
        )
        edge = GenreEdgeRule.objects.create(
            user=None, relation="secondary_parent", item_id="Q999999002", parent_item_id="Q999999003", action="add"
        )

        response = self._report(
            [
                _remap("canonical_parent", "Q999999001", "parent_item_id"),
                _remap("secondary_parents", "Q999999002\tQ999999003", "item_id", "Q999999002", "Q999999020"),
                _remap("secondary_parents", "Q999999002\tQ999999003", "parent_id", "Q999999003", "Q999999030"),
            ]
        )

        assert response.json()["remappedCount"] == 3
        main.refresh_from_db()
        edge.refresh_from_db()
        assert main.parent_item_id == NEW
        assert (edge.item_id, edge.parent_item_id) == ("Q999999020", "Q999999030")

    def test_remap_by_rule_id_then_rewritten(self):
        rule = GenreEdgeRule.objects.create(
            user=None,
            relation="canonical_parent",
            item_id="Q999999001",
            parent_item_id=OLD,
            exclude_other_parents=False,
        )

        response = self._report([{"rule_id": str(rule.uuid), "column": "parent_item_id", "from": OLD, "to": NEW}])

        assert response.json() == {"remappedCount": 1, "reviewCount": 0}
        rule.refresh_from_db()
        assert rule.parent_item_id == NEW

    def test_remap_by_rule_id_clashing_then_review_item_with_rule(self):
        rule = GenreEdgeRule.objects.create(
            user=None,
            relation="canonical_parent",
            item_id="Q999999001",
            parent_item_id=OLD,
            exclude_other_parents=False,
        )
        GenreEdgeRule.objects.create(
            user=None, relation="secondary_parent", item_id="Q999999001", parent_item_id=NEW, action="add"
        )

        response = self._report([{"rule_id": str(rule.uuid), "column": "parent_item_id", "from": OLD, "to": NEW}])

        assert response.json() == {"remappedCount": 0, "reviewCount": 1}
        [item] = self._review()
        assert (item["ruleId"], item["reason"], item["target"]) == (str(rule.uuid), "redirect_conflict", NEW)

    def test_rule_id_with_list_or_wrong_column_then_400(self):
        rule_id = "00000000-0000-0000-0000-000000000001"

        for item in (
            {"rule_id": rule_id, "list": "canonical_parent", "key": "Q1", "column": "item_id"},
            {"rule_id": rule_id, "column": "overview_item_id"},
        ):
            response = self._report([{**item, "from": OLD, "to": NEW}])
            assert response.status_code == status.HTTP_400_BAD_REQUEST, item

    def test_remap_onto_existing_or_exclusive_entry_then_review_item(self):
        _entry("technique_genres", OLD)
        _entry("technique_genres", NEW)
        _entry("theme_genres", "Q999999005")
        _entry("out_of_scope_genres", "Q999999006")

        response = self._report(
            [_remap("technique_genres", OLD), _remap("theme_genres", "Q999999005", old="Q999999005", new="Q999999006")]
        )

        assert response.json() == {"remappedCount": 0, "reviewCount": 2}
        assert CurationEntry.objects.filter(key=OLD).exists()
        assert [(i["key"], i["itemId"], i["reason"], i["target"]) for i in self._review()] == [
            (OLD, OLD, "redirect_conflict", NEW),
            ("Q999999005", "Q999999005", "redirect_conflict", "Q999999006"),
        ]
        assert all(i["evidence"] is None for i in self._review())

    def test_unknown_entry_or_already_fixed_then_skipped(self):
        _entry("technique_genres", "Q999999007")

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

    def test_rule_review_reasons_then_stored(self):
        for reason in ("invalid_rule", "exclusive_parent_regional"):
            item = {"list": "theme_genres", "key": OLD, "column": "item_id", "itemId": OLD, "reason": reason}
            assert self._report([], [item]).status_code == status.HTTP_200_OK
            [stored] = self._review()
            assert stored["reason"] == reason
        item["evidence"] = {"detail": "parent is regional, expected canonical"}
        assert self._report([], [item]).status_code == status.HTTP_200_OK
        assert self._review()[0]["evidence"] == {"detail": "parent is regional, expected canonical"}

    def test_review_evidence_then_round_trips(self):
        evidence = {
            "label": "Foo rock",
            "modified": "2026-10-01T12:00:00Z",
            "instanceOf": [{"id": "Q5", "label": "human"}, {"id": "Q999999011", "label": None}],
            "subclassOf": [],
            "hasIndigenousTo": False,
            "conflictList": "theme_genres",
        }
        item = {"list": "theme_genres", "key": OLD, "column": "item_id", "itemId": OLD, "reason": "not_in_tree"}

        response = self._report([], [{**item, "evidence": evidence}, {**item, "key": NEW, "evidence": None}])

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [i["evidence"] for i in self._review()] == [{**evidence, "modified": "2026-10-01T12:00:00+00:00"}, None]

    def test_invalid_evidence_then_400(self):
        item = {"list": "theme_genres", "key": OLD, "column": "item_id", "itemId": OLD, "reason": "not_in_tree"}
        for evidence in [
            {"comment": "x"},
            {"instanceOf": [{"id": "Q5", "label": "human", "extra": 1}]},
            {"instanceOf": [{"id": "bad", "label": None}]},
            {"conflictList": "nope"},
        ]:
            assert self._report([], [{**item, "evidence": evidence}]).status_code == status.HTTP_400_BAD_REQUEST
        assert CurationReviewItem.objects.count() == 0

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
