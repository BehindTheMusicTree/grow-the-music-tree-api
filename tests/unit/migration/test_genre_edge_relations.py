from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from tests.utils.AppTestCase import AppTestCase

migration_module = import_module("grow.migrations.0169_genre_edge_relations")
SEP = "\t"


class TestCase(AppTestCase):
    """Runs the data step against the head schema: the former `GenreEdgeRule` rows can't be inserted into it (its
    check constraints reject the old relations), so only the folded curation lists are exercised here."""

    def setUp(self):
        super().setUp()
        self.apps = MigrationLoader(connection).project_state(("grow", "0169_genre_edge_relations")).apps
        self.Entry = self.apps.get_model("grow", "CurationEntry")
        self.Rule = self.apps.get_model("grow", "GenreEdgeRule")
        self.ReviewItem = self.apps.get_model("grow", "CurationReviewItem")
        self.Rule.objects.all().delete()

    def _entry(self, list_name: str, key: str, reason="why", **values):
        return self.Entry.objects.create(list_name=list_name, key=key, values=values, reason=reason)

    def _rules(self) -> set[tuple]:
        return {(r.item_id, r.relation, r.target_item_id, r.action) for r in self.Rule.objects.all()}

    def _migrate(self):
        migration_module.convert_to_typed_edges(self.apps, None)

    def test_empty_database_then_nothing_happens(self):
        self._migrate()

        assert not self.Rule.objects.exists()

    def test_memberships_and_derivations_then_typed_rules(self):
        self._entry("regional_memberships", f"Q1{SEP}Q2", action="add")
        self._entry("regional_memberships", f"Q3{SEP}Q4", action="prohibit")
        self._entry("genre_derivations", f"Q5{SEP}Q6")

        self._migrate()

        assert self._rules() == {
            ("Q1", "classification", "Q2", "assert"),
            ("Q3", "classification", "Q4", "prohibit"),
            ("Q5", "derivation", "Q6", "assert"),
        }
        assert not self.Entry.objects.filter(list_name__in=migration_module.FOLDED_LISTS).exists()

    def test_decision_id_kept_else_entry_uuid(self):
        kept = self._entry("regional_memberships", f"Q1{SEP}Q2", action="add", decision_id="decision-1")
        plain = self._entry("genre_derivations", f"Q5{SEP}Q6")

        self._migrate()

        assert self.Rule.objects.get(item_id="Q1").decision_id == "decision-1"
        assert self.Rule.objects.get(item_id="Q5").decision_id == str(plain.uuid)
        assert kept.uuid != plain.uuid

    def test_review_items_follow_their_rule_and_orphans_go(self):
        entry = self._entry("genre_derivations", f"Q5{SEP}Q6")
        self.ReviewItem.objects.create(list_name="genre_derivations", key=f"Q5{SEP}Q6", column="origin_item_id")
        self.ReviewItem.objects.create(list_name="genre_derivations", key="Qgone", column="origin_item_id")

        self._migrate()

        item = self.ReviewItem.objects.get()
        assert (item.rule_id, item.list_name, item.key, item.column) == (entry.uuid, None, None, "target_item_id")

    def test_self_edge_then_refused(self):
        self._entry("genre_derivations", f"Q5{SEP}Q5")

        with pytest.raises(RuntimeError, match="its own parent"):
            self._migrate()

    def test_decision_id_already_used_then_refused(self):
        self._entry("regional_memberships", f"Q1{SEP}Q2", action="add", decision_id="dup")
        self._entry("regional_memberships", f"Q3{SEP}Q4", action="add", decision_id="dup")

        with pytest.raises(RuntimeError, match="already used"):
            self._migrate()

    def _fold(self, entry):
        return migration_module._fold_entry(entry, self.Rule)

    def test_same_triplet_same_action_then_merged_keeping_reason(self):
        rule = self.Rule.objects.create(
            item_id="Q1", relation="classification", target_item_id="Q2", action="assert", decision_id="d", reason=""
        )
        entry = self._entry("regional_memberships", f"Q1{SEP}Q2", reason="because", action="add")

        assert self._fold(entry) == rule.pk

        rule.refresh_from_db()
        assert (rule.decision_id, rule.reason) == ("d", "because")
        assert self.Rule.objects.count() == 1

    def test_same_triplet_opposite_action_then_refused(self):
        self.Rule.objects.create(
            item_id="Q1", relation="classification", target_item_id="Q2", action="prohibit", decision_id="d"
        )
        entry = self._entry("regional_memberships", f"Q1{SEP}Q2", action="add")

        with pytest.raises(RuntimeError, match="resolve it before migrating"):
            self._fold(entry)
