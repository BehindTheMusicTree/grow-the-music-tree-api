import csv
from pathlib import Path
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status

from grow.curation.edges import upsert_edge_row
from grow.curation.rows import InvalidRow
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.utils.AppTestCase import AppTestCase

SEED = Path(__file__).parents[3] / "grow" / "curation" / "seed" / "genre_edges.csv"
A, B, C = "Q999990001", "Q999990002", "Q999990003"


def _rule(**kwargs) -> GenreEdgeRule:
    fields = {
        "user": None,
        "relation": "classification",
        "item_id": A,
        "target_item_id": B,
        "action": "assert",
        "decision_id": f"d-{kwargs.get('relation', 'classification')}-{kwargs.get('action', 'assert')}-{id(kwargs)}",
    }
    return GenreEdgeRule(**{**fields, **kwargs})


class TestConstraints(AppTestCase):
    def _violates(self, **kwargs) -> None:
        # The database enforces the constraint even when the manager is bypassed.
        with self.assertRaises(IntegrityError), transaction.atomic():
            GenreEdgeRule.objects.bulk_create([_rule(**kwargs)])

    def test_self_edge_then_rejected(self):
        self._violates(target_item_id=A)

    def test_unknown_relation_or_action_then_rejected(self):
        self._violates(relation="nope")
        self._violates(action="add")

    def test_same_triplet_twice_then_rejected_whatever_the_action(self):
        GenreEdgeRule.objects.bulk_create([_rule(decision_id="first")])

        self._violates(decision_id="second")
        self._violates(action="prohibit", decision_id="third")

    def test_same_decision_id_twice_then_rejected(self):
        GenreEdgeRule.objects.bulk_create([_rule(decision_id="same")])

        self._violates(target_item_id=C, decision_id="same")

    def test_assert_and_prohibit_on_one_pair_with_different_relations_then_allowed(self):
        GenreEdgeRule.objects.bulk_create(
            [
                _rule(relation="classification", action="assert", decision_id="d1"),
                _rule(relation="derivation", action="prohibit", decision_id="d2"),
                _rule(relation="influence", action="assert", decision_id="d3"),
            ]
        )

        assert GenreEdgeRule.objects.filter(item_id=A, target_item_id=B).count() == 3

    def test_manager_validates_before_writing(self):
        with self.assertRaises(ValidationError):
            GenreEdgeRule.objects.create(
                user=None, relation="classification", item_id=A, target_item_id=A, action="assert"
            )


class TestManager(AppTestCase):
    def _history(self, uuid) -> list[str]:
        return [h.action for h in HistoryEntry.objects.filter(content_uuid=uuid).order_by("created_on")]

    def test_upsert_then_created_unchanged_updated(self):
        assert GenreEdgeRule.objects.upsert("classification", A, B, action="assert") == "created"
        assert GenreEdgeRule.objects.upsert("classification", A, B, action="assert") == "unchanged"
        assert GenreEdgeRule.objects.upsert("classification", A, B, action="prohibit") == "updated"

        rule = GenreEdgeRule.objects.get(item_id=A)
        assert self._history(rule.uuid) == [HistoryAction.CREATED, HistoryAction.UPDATED]

    def test_new_rule_then_default_decision_id_is_a_uuid(self):
        GenreEdgeRule.objects.upsert("derivation", A, B, action="assert")

        rule = GenreEdgeRule.objects.get(item_id=A)
        assert rule.decision_id == str(UUID(rule.decision_id))

    def test_update_then_decision_id_kept(self):
        GenreEdgeRule.objects.upsert("derivation", A, B, action="assert", decision_id="stable")

        GenreEdgeRule.objects.upsert("derivation", A, B, action="prohibit")

        assert GenreEdgeRule.objects.get(item_id=A).decision_id == "stable"

    def test_assert_and_prohibit_on_different_relations_then_both_kept(self):
        GenreEdgeRule.objects.upsert("classification", A, B, action="assert")
        GenreEdgeRule.objects.upsert("influence", A, B, action="prohibit")

        assert {(r.relation, r.action) for r in GenreEdgeRule.objects.filter(item_id=A)} == {
            ("classification", "assert"),
            ("influence", "prohibit"),
        }

    def test_unknown_relation_then_validation_error(self):
        with self.assertRaises(ValidationError):
            GenreEdgeRule.objects.upsert("secondary_parent", A, B, action="assert")

    def test_deletion_then_recorded_and_not_a_prohibition(self):
        GenreEdgeRule.objects.upsert("influence", A, B, action="assert")
        rule = GenreEdgeRule.objects.get(item_id=A)
        uuid = rule.uuid

        GenreEdgeRule.objects.delete_instance(rule)

        assert self._history(uuid) == [HistoryAction.CREATED, HistoryAction.DELETED]
        assert not GenreEdgeRule.objects.filter(item_id=A, action="prohibit").exists()


class TestEndpoints(AppTestCase):
    def _post(self, **body):
        return self.api_client.post(path=reverse("curation-edges"), data=body, format="json")

    def test_get_edge_then_200_and_unknown_then_404(self):
        uuid = self._post(relation="classification", itemId=A, targetItemId=B, action="assert").json()["uuid"]

        found = self.api_client.get(path=reverse("curation-edge", kwargs={"uuid": uuid}))
        missing = self.api_client.get(
            path=reverse("curation-edge", kwargs={"uuid": "00000000-0000-0000-0000-000000000000"})
        )

        assert found.status_code == status.HTTP_200_OK
        assert found.json()["uuid"] == uuid
        assert missing.status_code == status.HTTP_404_NOT_FOUND

    def test_create_list_patch_delete(self):
        created = self._post(relation="classification", itemId=A, targetItemId=B, action="assert")
        assert created.status_code == status.HTTP_201_CREATED, created.content
        uuid = created.json()["uuid"]

        listed = self.api_client.get(path=reverse("curation-edges"), data={"item_id": A})
        assert [r["row"].get("target_item_id", r["row"].get("targetItemId")) for r in listed.json()["results"]] == [B]

        patched = self.api_client.patch(
            path=reverse("curation-edge", kwargs={"uuid": uuid}), data={"reason": "edited"}, format="json"
        )
        assert patched.status_code == status.HTTP_200_OK
        assert GenreEdgeRule.objects.get(uuid=uuid).reason == "edited"

        deleted = self.api_client.delete(path=reverse("curation-edge", kwargs={"uuid": uuid}))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert not GenreEdgeRule.objects.filter(item_id=A).exists()

    def test_same_triplet_twice_then_400(self):
        self._post(relation="classification", itemId=A, targetItemId=B, action="assert")

        again = self._post(relation="classification", itemId=A, targetItemId=B, action="prohibit")

        assert again.status_code == status.HTTP_400_BAD_REQUEST
        assert GenreEdgeRule.objects.filter(item_id=A).count() == 1

    def test_assert_and_prohibit_on_different_relations_then_201(self):
        assert self._post(relation="classification", itemId=A, targetItemId=B, action="assert").status_code == 201
        assert self._post(relation="derivation", itemId=A, targetItemId=B, action="prohibit").status_code == 201

    def test_missing_target_then_400(self):
        response = self._post(relation="classification", itemId=A, action="assert")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not GenreEdgeRule.objects.filter(item_id=A).exists()

    def test_unknown_relation_or_action_then_400(self):
        assert self._post(relation="nope", itemId=A, targetItemId=B, action="assert").status_code == 400
        assert self._post(relation="classification", itemId=A, targetItemId=B, action="add").status_code == 400


class TestEdgeKindRules(AppTestCase):
    G1, G2, OV = "Q999990011", "Q999990012", "Q999990013"

    def _post(self, **body):
        return self.api_client.post(path=reverse("curation-edges"), data=body, format="json")

    def _global(self, *items: str) -> None:
        for item in items:
            CurationEntry.objects.create(
                user=None,
                list_name="global_roots",
                key=item,
                values={"decision_id": f"r-{item}", "decision_source": "gold"},
                reason="r",
            )

    def _overview(self, item: str) -> None:
        CurationEntry.objects.create(
            user=None,
            list_name="regional_overview_types",
            key=item,
            values={"decision_id": f"o-{item}", "decision_source": "gold", "overview_type": "current"},
            reason="r",
        )

    def test_second_assert_to_a_global_genre_then_400(self):
        self._global(self.G1, self.G2)
        first = self._post(relation="classification", itemId=A, targetItemId=self.G1, action="assert")
        second = self._post(relation="classification", itemId=A, targetItemId=self.G2, action="assert")

        assert first.status_code == status.HTTP_201_CREATED, first.content
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert GenreEdgeRule.objects.filter(item_id=A).count() == 1

    def test_overview_classified_under_a_genre_then_400(self):
        self._global(self.G1)
        self._overview(self.OV)

        response = self._post(relation="classification", itemId=self.OV, targetItemId=self.G1, action="assert")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not GenreEdgeRule.objects.filter(item_id=self.OV).exists()

    def test_derivation_or_influence_touching_an_overview_then_400(self):
        self._overview(self.OV)

        for relation in ("derivation", "influence"):
            as_item = self._post(relation=relation, itemId=self.OV, targetItemId=A, action="assert")
            as_target = self._post(relation=relation, itemId=A, targetItemId=self.OV, action="assert")
            assert as_item.status_code == status.HTTP_400_BAD_REQUEST, relation
            assert as_target.status_code == status.HTTP_400_BAD_REQUEST, relation
        assert not GenreEdgeRule.objects.filter(item_id__in=[self.OV, A]).exists()


class TestExportAndSeed(AppTestCase):
    def _seed_rows(self) -> list[dict[str, str]]:
        with SEED.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_seeded_rules_then_export_edges_equal_csv(self):
        export = self.api_client.get(path=reverse("curation-export")).json()

        key = lambda r: (r["item_id"], r["relation"], r["target_item_id"])  # noqa: E731
        # The migrated rules got their decision_id from their uuid, the CSV carries the curators' own.
        strip = lambda rows: sorted(({k: v for k, v in r.items() if k != "decision_id"} for r in rows), key=key)  # noqa: E731
        assert strip(export["edges"]) == strip(self._seed_rows())

    def test_import_row_with_invalid_edge_then_invalid_row(self):
        with self.assertRaises(InvalidRow):
            upsert_edge_row(
                {
                    "decision_id": "",
                    "relation": "classification",
                    "item_id": A,
                    "target_item_id": A,
                    "action": "assert",
                    "reason": "r",
                }
            )


class TestHistoryByList(AppTestCase):
    def test_edges_list_filter_then_edge_history(self):
        GenreEdgeRule.objects.upsert("derivation", A, B, action="assert")

        response = self.api_client.get(path=reverse("curation-history"), data={"list": "genre_edges"})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [h["entry"] for h in response.json()["results"]] == [str(GenreEdgeRule.objects.get(item_id=A).uuid)]

    def test_retired_list_filter_then_accepted(self):
        response = self.api_client.get(path=reverse("curation-history"), data={"list": "regional_memberships"})

        assert response.status_code == status.HTTP_200_OK
