import csv
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status

from grow.curation.edges import project_legacy_lists, upsert_edge_row
from grow.curation.rows import InvalidRow
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.utils.AppTestCase import AppTestCase

SEED = Path(__file__).parents[3] / "grow" / "curation" / "seed" / "genre_edges.csv"
A, B, C = "Q999990001", "Q999990002", "Q999990003"


def _rule(**kwargs) -> GenreEdgeRule:
    fields = {
        "user": None,
        "relation": "canonical_parent",
        "item_id": A,
        "parent_item_id": B,
        "exclude_other_parents": False,
    }
    return GenreEdgeRule(**{**fields, **kwargs})


class TestConstraints(AppTestCase):
    def _violates(self, **kwargs) -> None:
        # The database enforces the constraint even when the manager is bypassed.
        with self.assertRaises(IntegrityError), transaction.atomic():
            GenreEdgeRule.objects.bulk_create([_rule(**kwargs)])

    def test_self_edge_then_rejected(self):
        self._violates(parent_item_id=A)

    def test_root_on_non_canonical_relation_then_rejected(self):
        self._violates(relation="regional_overview", parent_item_id=None, exclude_other_parents=True)

    def test_root_without_exclusion_then_rejected(self):
        self._violates(parent_item_id=None, exclude_other_parents=False)

    def test_action_only_on_secondary_then_rejected(self):
        self._violates(action="add")
        self._violates(relation="secondary_parent", exclude_other_parents=None, action=None)

    def test_exclusion_flag_only_off_secondary_then_rejected(self):
        self._violates(exclude_other_parents=None)
        self._violates(relation="secondary_parent", action="add", exclude_other_parents=False)

    def test_second_primary_parent_or_second_rule_for_pair_then_rejected(self):
        GenreEdgeRule.objects.bulk_create([_rule()])
        self._violates(parent_item_id=C)
        self._violates(relation="regional_overview")

    def test_manager_validates_before_writing(self):
        with self.assertRaises(ValidationError):
            GenreEdgeRule.objects.create(
                user=None, relation="canonical_parent", item_id=A, parent_item_id=A, exclude_other_parents=False
            )


class TestManager(AppTestCase):
    def _history(self, uuid) -> list[str]:
        return [h.action for h in HistoryEntry.objects.filter(content_uuid=uuid).order_by("created_on")]

    def test_upsert_then_created_unchanged_updated(self):
        assert GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=False) == "created"
        assert GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=False) == "unchanged"
        assert GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=True) == "updated"

        rule = GenreEdgeRule.objects.get(item_id=A)
        assert self._history(rule.uuid) == [HistoryAction.CREATED, HistoryAction.UPDATED]

    def test_new_primary_parent_then_replaces_previous_one(self):
        GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=True)

        GenreEdgeRule.objects.upsert("canonical_parent", A, C, exclude_other_parents=True)

        assert list(GenreEdgeRule.objects.filter(item_id=A).values_list("parent_item_id", flat=True)) == [C]

    def test_root_then_replaces_parent_and_back(self):
        GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=True)

        GenreEdgeRule.objects.upsert("canonical_parent", A, None, exclude_other_parents=True)
        assert list(GenreEdgeRule.objects.filter(item_id=A).values_list("parent_item_id", flat=True)) == [None]

        GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=True)
        assert list(GenreEdgeRule.objects.filter(item_id=A).values_list("parent_item_id", flat=True)) == [B]

    def test_secondary_on_the_main_parent_then_replaces_it(self):
        GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=True)

        GenreEdgeRule.objects.upsert("secondary_parent", A, B, action="add")

        assert [(r.relation, r.action) for r in GenreEdgeRule.objects.filter(item_id=A)] == [
            ("secondary_parent", "add")
        ]

    def test_invalid_root_then_validation_error(self):
        with self.assertRaises(ValidationError):
            GenreEdgeRule.objects.upsert("regional_overview", A, None, exclude_other_parents=True)

    def test_deletion_then_recorded(self):
        GenreEdgeRule.objects.upsert("regional_overview", A, B, exclude_other_parents=False)
        rule = GenreEdgeRule.objects.get(item_id=A)
        uuid = rule.uuid

        GenreEdgeRule.objects.delete_instance(rule)

        assert self._history(uuid) == [HistoryAction.CREATED, HistoryAction.DELETED]


class TestEndpoints(AppTestCase):
    def _post(self, **body):
        return self.api_client.post(path=reverse("curation-edges"), data=body, format="json")

    def test_create_list_patch_delete(self):
        created = self._post(relation="canonical_parent", itemId=A, parentItemId=B, excludeOtherParents=True)
        assert created.status_code == status.HTTP_201_CREATED, created.content
        uuid = created.json()["uuid"]

        listed = self.api_client.get(path=reverse("curation-edges"), data={"item_id": A})
        assert [
            r["row"]["parent_item_id"] if "parent_item_id" in r["row"] else r["row"]["parentItemId"]
            for r in listed.json()["results"]
        ] == [B]

        patched = self.api_client.patch(
            path=reverse("curation-edge", kwargs={"uuid": uuid}), data={"reason": "edited"}, format="json"
        )
        assert patched.status_code == status.HTTP_200_OK
        assert GenreEdgeRule.objects.get(uuid=uuid).reason == "edited"

        deleted = self.api_client.delete(path=reverse("curation-edge", kwargs={"uuid": uuid}))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert not GenreEdgeRule.objects.filter(item_id=A).exists()

    def test_root_on_regional_relation_then_400(self):
        response = self._post(relation="regional_overview", itemId=A, excludeOtherParents=True)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not GenreEdgeRule.objects.filter(item_id=A).exists()

    def test_second_primary_parent_then_replaced_not_duplicated(self):
        self._post(relation="canonical_parent", itemId=A, parentItemId=B, excludeOtherParents=True)
        self._post(relation="canonical_parent", itemId=A, parentItemId=C, excludeOtherParents=True)

        assert GenreEdgeRule.objects.filter(item_id=A).count() == 1

    def test_unknown_relation_then_400(self):
        assert self._post(relation="nope", itemId=A).status_code == status.HTTP_400_BAD_REQUEST


class TestExportAndSeed(AppTestCase):
    def _seed_rows(self) -> list[dict[str, str]]:
        with SEED.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_seeded_rules_then_export_edges_equal_csv(self):
        export = self.api_client.get(path=reverse("curation-export")).json()

        key = lambda r: (r["item_id"], r["relation"], r["parent_item_id"])  # noqa: E731
        assert sorted(export["edges"], key=key) == sorted(self._seed_rows(), key=key)

    def test_legacy_projection_then_one_row_per_edge(self):
        GenreEdgeRule.objects.all().delete()
        GenreEdgeRule.objects.upsert("canonical_parent", A, B, exclude_other_parents=True, reason="r")
        GenreEdgeRule.objects.upsert("canonical_parent", C, None, exclude_other_parents=True, reason="r")
        GenreEdgeRule.objects.upsert("secondary_parent", A, C, action="add", reason="r")

        projection = project_legacy_lists()

        assert [r["item_id"] for r in projection["canonical_parent"]] == [A]
        assert [r["item_id"] for r in projection["accepted_canonical_roots"]] == [C]
        assert [(r["item_id"], r["parent_id"]) for r in projection["secondary_parents"]] == [(A, C)]

    def test_import_row_with_invalid_edge_then_invalid_row(self):
        with self.assertRaises(InvalidRow):
            upsert_edge_row(
                {
                    "relation": "canonical_parent",
                    "item_id": A,
                    "parent_item_id": A,
                    "action": "",
                    "exclude_other_parents": "true",
                    "reason": "r",
                }
            )


class TestHistoryByLegacyList(AppTestCase):
    def test_legacy_list_filter_then_edge_history(self):
        GenreEdgeRule.objects.upsert("regional_overview", A, B, exclude_other_parents=False)
        GenreEdgeRule.objects.upsert("canonical_parent", C, B, exclude_other_parents=True)

        response = self.api_client.get(path=reverse("curation-history"), data={"list": "regional_overviews"})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [h["entry"] for h in response.json()["results"]] == [str(GenreEdgeRule.objects.get(item_id=A).uuid)]
