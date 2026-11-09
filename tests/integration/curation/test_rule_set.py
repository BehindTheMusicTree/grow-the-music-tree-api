from django.urls import reverse
from rest_framework import status

from grow.curation.rows import InvalidRow, RowConflict, check_edit
from grow.curation.rule_set import find_rule_set_violations
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
from tests.utils.AppTestCase import AppTestCase

A, B = "Q999991001", "Q999991002"


def _exclude(list_name: str, item_id: str) -> None:
    CurationEntry.objects.create(user=None, list_name=list_name, key=item_id, values={}, reason="r")


def _root(item_id: str) -> None:
    GenreEdgeRule.objects.upsert("canonical_parent", item_id, None, exclude_other_parents=True, reason="r")


def _violations() -> list:
    return find_rule_set_violations(CurationEntry.objects.filter(user=None), GenreEdgeRule.objects.filter(user=None))


class TestRootRegionalConflict(AppTestCase):
    def test_regional_rule_on_a_root_then_invalid_row(self):
        _root(A)

        with self.assertRaises(InvalidRow) as raised:
            GenreEdgeRule.objects.upsert("regional_overview", A, B, exclude_other_parents=False, reason="r")

        assert "accepted canonical root" in raised.exception.errors["item_id"]

    def test_root_on_a_regional_item_then_invalid_row(self):
        GenreEdgeRule.objects.upsert("regional_genre_parent", A, B, exclude_other_parents=False, reason="r")

        with self.assertRaises(InvalidRow):
            _root(A)

    def test_stored_conflict_then_found_and_export_409(self):
        GenreEdgeRule.objects.bulk_create(
            [
                GenreEdgeRule(user=None, relation="canonical_parent", item_id=A, exclude_other_parents=True),
                GenreEdgeRule(
                    user=None, relation="regional_overview", item_id=A, parent_item_id=B, exclude_other_parents=False
                ),
            ]
        )

        assert [v.kind for v in _violations()] == ["root_regional"]
        response = self.api_client.get(path=reverse("curation-export"))
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["violations"][0]["item_ids"] == [A]

    def test_valid_state_then_no_violation_and_export_200(self):
        assert _violations() == []
        assert self.api_client.get(path=reverse("curation-export")).status_code == status.HTTP_200_OK


class TestExcludedEdgeConflict(AppTestCase):
    def test_edge_on_an_excluded_item_then_invalid_row(self):
        _exclude("theme_genres", A)

        with self.assertRaises(InvalidRow) as raised:
            GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=False, reason="r")

        assert "theme_genres" in raised.exception.errors["item_id"]

    def test_excluding_an_item_with_an_edge_then_row_conflict(self):
        GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=False, reason="r")

        with self.assertRaises(RowConflict):
            check_edit(CurationEntry.objects.filter(user=None), "theme_genres", {"item_id": A, "reason": "r"})

    def test_unrelated_stored_violation_then_edit_still_allowed(self):
        _exclude("theme_genres", A)
        GenreEdgeRule.objects.bulk_create(
            [
                GenreEdgeRule(
                    user=None, relation="canonical_parent", item_id=A, parent_item_id=B, exclude_other_parents=False
                )
            ]
        )

        assert [v.kind for v in _violations()] == ["excluded_edge"]
        assert (
            GenreEdgeRule.objects.upsert("canonical_parent", "Q999991003", B, exclude_other_parents=False, reason="r")
            == "created"
        )

    def test_item_in_two_exclusive_lists_then_exclusivity_violation(self):
        _exclude("theme_genres", A)
        _exclude("technique_genres", A)

        assert "exclusivity" in {v.kind for v in _violations()}


class TestStoredViolationsDontBlockOthers(AppTestCase):
    def test_rule_under_a_conflicted_root_then_created(self):
        GenreEdgeRule.objects.bulk_create(
            [
                GenreEdgeRule(user=None, relation="canonical_parent", item_id=A, exclude_other_parents=True),
                GenreEdgeRule(
                    user=None, relation="regional_overview", item_id=A, parent_item_id=B, exclude_other_parents=False
                ),
            ]
        )

        assert (
            GenreEdgeRule.objects.upsert("canonical_parent", "Q999991003", A, exclude_other_parents=False) == "created"
        )

    def test_remove_rule_on_an_excluded_item_then_allowed(self):
        _exclude("theme_genres", A)

        GenreEdgeRule.objects.upsert("secondary_parent", A, B, action="remove", reason="r")

        assert _violations() == []
