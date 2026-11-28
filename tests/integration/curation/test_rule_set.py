from django.urls import reverse
from rest_framework import status

from grow.curation.rows import InvalidRow, RowConflict, check_edit, find_graph_removal_error
from grow.curation.rule_set import find_rule_set_violations
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
from tests.utils.AppTestCase import AppTestCase
from tests.utils.ModelFixtureFactory import ModelFixtureFactory
from tests.utils.openapi import assert_response_matches_schema

A, B = "Q999991001", "Q999991002"


def _exclude(list_name: str, item_id: str) -> None:
    CurationEntry.objects.create(user=None, list_name=list_name, key=item_id, values={}, reason="r")


def _root(item_id: str) -> None:
    _graph("global_roots", item_id, f"root-{item_id}")


def _edge(relation: str, item_id: str, target_item_id: str, action: str = "assert") -> None:
    GenreEdgeRule.objects.bulk_create(
        [GenreEdgeRule(user=None, relation=relation, item_id=item_id, target_item_id=target_item_id, action=action)]
    )


def _violations() -> list:
    return find_rule_set_violations(CurationEntry.objects.filter(user=None), GenreEdgeRule.objects.filter(user=None))


class TestRootRegionalConflict(AppTestCase):
    def test_regional_rule_on_a_root_then_invalid_row(self):
        _root(A)

        with self.assertRaises(InvalidRow) as raised:
            GenreEdgeRule.objects.upsert("classification", A, B, action="assert", reason="r")

        assert "accepted global root" in raised.exception.errors["item_id"]

    def test_root_on_a_regional_item_then_invalid_row(self):
        GenreEdgeRule.objects.upsert("classification", A, B, action="assert", reason="r")

        with self.assertRaises(RowConflict):
            check_edit(
                CurationEntry.objects.filter(user=None),
                "global_roots",
                {"item_id": A, "decision_id": "d", "decision_source": "gold", "reason": "r"},
            )

    def test_stored_conflict_then_found_and_export_409(self):
        _root(A)
        _edge("classification", A, B)

        assert [v.kind for v in _violations()] == ["root_parent"]
        response = self.api_client.get(path=reverse("curation-export"))
        assert response.status_code == status.HTTP_409_CONFLICT
        assert assert_response_matches_schema(response, reverse("curation-export"))["violations"][0]["item_ids"] == [A]

    def test_valid_state_then_no_violation_and_export_200(self):
        assert _violations() == []
        assert self.api_client.get(path=reverse("curation-export")).status_code == status.HTTP_200_OK


class TestExcludedEdgeConflict(AppTestCase):
    def test_edge_on_an_excluded_item_then_invalid_row(self):
        _exclude("theme_genres", A)

        with self.assertRaises(InvalidRow) as raised:
            GenreEdgeRule.objects.upsert("classification", A, B, action="assert", reason="r")

        assert "theme_genres" in raised.exception.errors["item_id"]

    def test_excluding_an_item_with_an_edge_then_row_conflict(self):
        GenreEdgeRule.objects.upsert("classification", A, B, action="assert", reason="r")

        with self.assertRaises(RowConflict):
            check_edit(CurationEntry.objects.filter(user=None), "theme_genres", {"item_id": A, "reason": "r"})

    def test_unrelated_stored_violation_then_edit_still_allowed(self):
        _exclude("theme_genres", A)
        _edge("classification", A, B)

        assert [v.kind for v in _violations()] == ["excluded_edge"]
        assert GenreEdgeRule.objects.upsert("classification", "Q999991003", B, action="assert", reason="r") == "created"

    def test_item_in_two_exclusive_lists_then_exclusivity_violation(self):
        _exclude("theme_genres", A)
        _exclude("technique_genres", A)

        assert "exclusivity" in {v.kind for v in _violations()}


class TestStoredViolationsDontBlockOthers(AppTestCase):
    def test_rule_under_a_conflicted_root_then_created(self):
        _root(A)
        _edge("classification", A, B)

        assert GenreEdgeRule.objects.upsert("classification", "Q999991003", A, action="assert") == "created"

    def test_remove_rule_on_an_excluded_item_then_allowed(self):
        _exclude("theme_genres", A)

        GenreEdgeRule.objects.upsert("classification", A, B, action="prohibit", reason="r")

        assert _violations() == []


def _graph(list_name: str, key: str, decision: str, **values: str) -> None:
    CurationEntry.objects.create(
        user=None,
        list_name=list_name,
        key=key,
        values={**values, "decision_id": decision, "decision_source": "gold"},
        reason="r",
    )


def _local(item: str, kind: str, decision: str) -> None:
    _graph("local_identities", item, decision, kind=kind, label=item)


def _kinds() -> list[str]:
    return sorted(v.kind for v in _violations())


class TestGraphViolations(AppTestCase):
    def test_reused_decision_then_duplicate_decision_and_export_409(self):
        _graph("global_roots", "Q1", "d1")
        _graph("global_roots", "Q2", "d1")

        assert _kinds() == ["duplicate_decision"]
        assert self.api_client.get(path=reverse("curation-export")).status_code == status.HTTP_409_CONFLICT

    def test_undeclared_local_then_violation(self):
        _graph("regional_anchorings", "Q1\tLOCAL:ghost", "d1")

        assert _kinds() == ["undeclared_local"]

    def test_wrong_local_kind_then_violation(self):
        _local("LOCAL:genre-a", "genre", "d1")
        _graph("regional_anchorings", "Q1\tLOCAL:genre-a", "d2")

        assert _kinds() == ["local_kind"]

    def test_overview_classified_under_local_genre_then_violation(self):
        _local("LOCAL:genre-a", "genre", "d1")
        _local("LOCAL:over-a", "overview", "d2")
        _edge("classification", "LOCAL:over-a", "LOCAL:genre-a")

        assert _kinds() == ["local_kind"]

    def test_overview_as_derivation_end_then_violation(self):
        _local("LOCAL:over-a", "overview", "d1")
        _edge("derivation", "Q1", "LOCAL:over-a")

        assert _kinds() == ["local_kind"]

    def test_overview_as_influence_end_then_violation(self):
        _local("LOCAL:over-a", "overview", "d1")
        _edge("influence", "LOCAL:over-a", "Q1", "prohibit")

        assert _kinds() == ["local_kind"]

    def test_genre_derivation_then_no_violation(self):
        _local("LOCAL:genre-a", "genre", "d1")
        _edge("derivation", "LOCAL:genre-a", "Q1")

        assert _kinds() == []

    def test_classification_cycle_then_violation(self):
        _local("LOCAL:a", "overview", "d1")
        _local("LOCAL:b", "overview", "d2")
        _edge("classification", "LOCAL:a", "LOCAL:b")
        _edge("classification", "LOCAL:b", "LOCAL:a")

        assert _kinds() == ["classification_cycle"]

    def test_prohibited_classification_cycle_then_no_violation(self):
        _local("LOCAL:a", "overview", "d1")
        _local("LOCAL:b", "overview", "d2")
        _edge("classification", "LOCAL:a", "LOCAL:b")
        _edge("classification", "LOCAL:b", "LOCAL:a", "prohibit")

        assert _violations() == []

    def test_second_global_parent_then_violation(self):
        ModelFixtureFactory(None).create_genre("P1", wikidata_id="Q999991010")
        ModelFixtureFactory(None).create_genre("P2", wikidata_id="Q999991011")
        _local("LOCAL:x", "genre", "d1")
        _edge("classification", "LOCAL:x", "Q999991010")
        _edge("classification", "LOCAL:x", "Q999991011")

        assert "second_global_parent" in _kinds()

    def test_consistent_graph_then_export_200(self):
        _local("LOCAL:a", "overview", "d1")
        _graph("regional_anchorings", "Q1\tLOCAL:a", "d2")

        assert _violations() == []
        assert self.api_client.get(path=reverse("curation-export")).status_code == status.HTTP_200_OK


class TestMergeLocals(AppTestCase):
    def test_merge_naming_undeclared_local_then_violation(self):
        _graph("genre_merges", "LOCAL:x\tQ1", "d1")

        assert _kinds() == ["undeclared_local"]

    def test_merge_local_declared_by_addition_list_then_no_violation(self):
        CurationEntry.objects.create(
            user=None,
            list_name="global_parent_additions",
            key="LOCAL:x",
            values={"item_id": "LOCAL:x", "label": "x", "reason": "r"},
            reason="r",
        )
        _root("LOCAL:x")
        _graph("genre_merges", "LOCAL:x\tQ1", "d1")

        assert _violations() == []

    def test_derivation_local_declared_by_addition_list_then_no_violation(self):
        CurationEntry.objects.create(
            user=None,
            list_name="global_parent_additions",
            key="LOCAL:x",
            values={"item_id": "LOCAL:x", "label": "x", "reason": "r"},
            reason="r",
        )
        _root("LOCAL:x")
        _edge("derivation", "LOCAL:x", "Q1")

        assert _violations() == []

    def test_derivation_naming_undeclared_local_then_violation(self):
        _edge("derivation", "LOCAL:x", "Q1")

        assert _kinds() == ["undeclared_local"]

    def test_merge_local_declared_by_local_identity_then_no_violation(self):
        _local("LOCAL:x", "genre", "d1")
        _graph("genre_merges", "LOCAL:x\tQ1", "d2")

        assert _violations() == []


class TestLocalGenreGuards(AppTestCase):
    def _held(self, item_id="LOCAL:x"):

        ModelFixtureFactory(None).create_genre("X", wikidata_id=item_id)
        CurationEntry.objects.create(
            user=None,
            list_name="global_parent_additions",
            key=item_id,
            values={"item_id": item_id, "label": "x", "reason": "r"},
            reason="r",
        )
        _root(item_id)

    def test_unplaced_declared_local_then_violation(self):
        CurationEntry.objects.create(
            user=None,
            list_name="global_parent_additions",
            key="LOCAL:x",
            values={"item_id": "LOCAL:x", "label": "x", "reason": "r"},
            reason="r",
        )

        assert [v.kind for v in _violations()] == ["local_addition_unplaced"]

    def test_deleting_addition_of_held_genre_then_conflict(self):

        self._held()
        entry = CurationEntry.objects.get(list_name="global_parent_additions", key="LOCAL:x")

        assert "LOCAL:x" in find_graph_removal_error(CurationEntry.objects.filter(user=None), entry)

    def test_deleting_root_of_held_genre_then_conflict(self):

        self._held()
        entry = CurationEntry.objects.get(list_name="global_roots", key="LOCAL:x")

        assert "LOCAL:x" in find_graph_removal_error(CurationEntry.objects.filter(user=None), entry)

    def test_deleting_addition_without_genre_then_allowed(self):

        self._held()

        Genre.objects.filter(wikidata_id="LOCAL:x").delete()
        CurationEntry.objects.filter(list_name="global_roots", key="LOCAL:x").delete()
        entry = CurationEntry.objects.get(list_name="global_parent_additions", key="LOCAL:x")

        assert find_graph_removal_error(CurationEntry.objects.filter(user=None), entry) is None
