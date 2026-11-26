import importlib

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from tests.utils.AppTestCase import AppTestCase
from tests.utils.ModelFixtureFactory import ModelFixtureFactory

tree_name = importlib.import_module("grow.migrations.0168_criteria_tree_name_global")
list_names = importlib.import_module("grow.migrations.0170_curation_list_global_names")


class TestTreeNameMigration(AppTestCase):
    def setUp(self):
        super().setUp()
        self.apps = MigrationLoader(connection).project_state(("grow", "0170_curation_list_global_names")).apps
        self.criteria = self.apps.get_model("grow", "Criteria").objects

    def _two_rows(self, first: str, second: str):
        factory = ModelFixtureFactory(None)
        pks = [factory.create_genre("Alpha").pk, factory.create_genre("Beta").pk]
        self.criteria.filter(pk=pks[0]).update(tree_name=first)
        self.criteria.filter(pk=pks[1]).update(tree_name=second)
        self.pks = pks

    def test_forward_then_canonical_becomes_global_and_regional_untouched(self):
        self._two_rows("canonical", "regional")

        tree_name.forward(self.apps, None)

        assert sorted(self.criteria.filter(pk__in=self.pks).values_list("tree_name", flat=True)) == [
            "global",
            "regional",
        ]

    def test_backward_then_global_becomes_canonical(self):
        self._two_rows("global", "regional")

        tree_name.backward(self.apps, None)

        assert sorted(self.criteria.filter(pk__in=self.pks).values_list("tree_name", flat=True)) == [
            "canonical",
            "regional",
        ]


class TestListNamesMigration(AppTestCase):
    def setUp(self):
        super().setUp()
        self.apps = MigrationLoader(connection).project_state(("grow", "0170_curation_list_global_names")).apps
        self.entries = self.apps.get_model("grow", "CurationEntry").objects
        self.entries.all().delete()

    def _entry(self, list_name: str, key: str):
        return self.entries.create(user=None, list_name=list_name, key=key, values={}, reason="r")

    def test_forward_then_lists_renamed_and_others_untouched(self):
        self._entry("canonical_roots", "Q1")
        self._entry("forced_canonical_genres", "Q2")
        self._entry("regional_anchorings", "Q3")

        list_names.forward(self.apps, None)

        assert dict(self.entries.values_list("key", "list_name")) == {
            "Q1": "global_roots",
            "Q2": "forced_global_genres",
            "Q3": "regional_anchorings",
        }

    def test_backward_then_old_names_restored(self):
        self._entry("global_roots", "Q1")
        self._entry("global_genre_pop_side", "Q2")

        list_names.backward(self.apps, None)

        assert dict(self.entries.values_list("key", "list_name")) == {
            "Q1": "canonical_roots",
            "Q2": "canonical_genre_pop_side",
        }

    def test_forward_then_exclusive_parent_regional_alerts_dropped(self):
        items = self.apps.get_model("grow", "CurationReviewItem").objects
        items.create(list_name="x", key="k", column="item_id", reason="exclusive_parent_regional", evidence={})

        list_names.forward(self.apps, None)

        assert not items.filter(reason="exclusive_parent_regional").exists()
