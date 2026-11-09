from importlib import import_module

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from tests.utils.AppTestCase import AppTestCase

migration_module = import_module("grow.migrations.0112_genre_edge_rules")
SEP = "\t"


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.apps = MigrationLoader(connection).project_state(("grow", "0112_genre_edge_rules")).apps
        self.Entry = self.apps.get_model("grow", "CurationEntry")
        self.Rule = self.apps.get_model("grow", "GenreEdgeRule")
        self.ReviewItem = self.apps.get_model("grow", "CurationReviewItem")
        self.Rule.objects.all().delete()

    def _entry(self, list_name: str, key: str, **values):
        return self.Entry.objects.create(list_name=list_name, key=key, values=values, reason="why")

    def _legacy_entries(self):
        self._entry("canonical_parent", "Q1", parent_item_id="Q2", exclude_other_parents=True)
        self._entry("canonical_parent", "Q3", parent_item_id="Q4", exclude_other_parents="false")
        self._entry("accepted_canonical_roots", "Q5")
        self._entry("regional_genre_parent", "Q6", parent_item_id="Q7", exclude_other_parents=False)
        self._entry("regional_overviews", f"Q8{SEP}Q9", exclude_other_parents=True)
        self._entry("secondary_parents", f"Q10{SEP}Q11", action="remove")

    def _rules(self) -> set[tuple]:
        return {
            (r.relation, r.item_id, r.parent_item_id, r.action, r.exclude_other_parents)
            for r in self.Rule.objects.all()
        }

    def test_forward_then_entries_become_rules(self):
        self._legacy_entries()

        migration_module.entries_to_edge_rules(self.apps, None)

        assert self._rules() == {
            ("canonical_parent", "Q1", "Q2", None, True),
            ("canonical_parent", "Q3", "Q4", None, False),
            ("canonical_parent", "Q5", None, None, True),
            ("regional_genre_parent", "Q6", "Q7", None, False),
            ("regional_overview", "Q8", "Q9", None, True),
            ("secondary_parent", "Q10", "Q11", "remove", None),
        }
        assert not self.Entry.objects.filter(list_name__in=migration_module.LEGACY_LISTS).exists()

    def test_forward_then_review_items_follow_their_rule(self):
        entry = self._entry("canonical_parent", "Q1", parent_item_id="Q2", exclude_other_parents=True)
        self.ReviewItem.objects.create(list_name="canonical_parent", key="Q1")
        self.ReviewItem.objects.create(list_name="canonical_parent", key="Qgone")

        migration_module.entries_to_edge_rules(self.apps, None)

        item = self.ReviewItem.objects.get()
        assert (item.rule_id, item.list_name, item.key) == (entry.uuid, None, None)

    def test_reverse_then_rules_become_entries(self):
        self._legacy_entries()
        migration_module.entries_to_edge_rules(self.apps, None)
        rule = self.Rule.objects.get(item_id="Q1")
        self.ReviewItem.objects.create(rule=rule)

        migration_module.edge_rules_to_entries(self.apps, None)

        restored = {
            (e.list_name, e.key): e.values
            for e in self.Entry.objects.filter(list_name__in=migration_module.LEGACY_LISTS)
        }
        assert restored == {
            ("canonical_parent", "Q1"): {"parent_item_id": "Q2", "exclude_other_parents": True},
            ("canonical_parent", "Q3"): {"parent_item_id": "Q4", "exclude_other_parents": False},
            ("accepted_canonical_roots", "Q5"): {},
            ("regional_genre_parent", "Q6"): {"parent_item_id": "Q7", "exclude_other_parents": False},
            ("regional_overviews", f"Q8{SEP}Q9"): {"exclude_other_parents": True},
            ("secondary_parents", f"Q10{SEP}Q11"): {"action": "remove"},
        }
        item = self.ReviewItem.objects.get()
        assert (item.rule_id, item.list_name, item.key) == (None, "canonical_parent", "Q1")
        assert not self.Rule.objects.exists()

    def test_two_primary_parents_then_migration_refuses(self):
        self._entry("canonical_parent", "Q1", parent_item_id="Q2", exclude_other_parents=True)
        self._entry("accepted_canonical_roots", "Q1")

        with self.assertRaisesRegex(RuntimeError, "set the same canonical_parent"):
            migration_module.entries_to_edge_rules(self.apps, None)

    def test_several_regional_overviews_then_all_migrate(self):
        self._entry("regional_overviews", f"Q1{SEP}Q2", exclude_other_parents=False)
        self._entry("regional_overviews", f"Q1{SEP}Q3", exclude_other_parents=False)

        migration_module.entries_to_edge_rules(self.apps, None)

        assert self._rules() == {
            ("regional_overview", "Q1", "Q2", None, False),
            ("regional_overview", "Q1", "Q3", None, False),
        }

    def test_same_pair_twice_then_migration_refuses(self):
        self._entry("canonical_parent", "Q1", parent_item_id="Q2", exclude_other_parents=True)
        self._entry("secondary_parents", f"Q1{SEP}Q2", action="add")

        with self.assertRaisesRegex(RuntimeError, "link Q1 to Q2"):
            migration_module.entries_to_edge_rules(self.apps, None)

    def test_root_that_is_also_regional_then_migration_refuses(self):
        self._entry("accepted_canonical_roots", "Q1")
        self._entry("regional_genre_parent", "Q1", parent_item_id="Q2", exclude_other_parents=False)

        with self.assertRaisesRegex(RuntimeError, "both an accepted canonical root and regional"):
            migration_module.entries_to_edge_rules(self.apps, None)

    def test_self_parent_then_migration_refuses(self):
        self._entry("canonical_parent", "Q1", parent_item_id="Q1", exclude_other_parents=False)

        with self.assertRaisesRegex(RuntimeError, "own parent"):
            migration_module.entries_to_edge_rules(self.apps, None)
