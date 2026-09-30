from importlib import import_module

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from tests.utils.AppTestCase import AppTestCase

migration_module = import_module("grow.migrations.0033_criteria_tree_name")


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        # Recreates the mid-migration schema/state: `tree_name` added, `allows_multiple_primary_parents` not yet removed.
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE grow_criteria ADD COLUMN allows_multiple_primary_parents bool NOT NULL DEFAULT 0"
            )
        state = MigrationLoader(connection).project_state(("grow", "0032_historyentry_actor"))
        migration_module.Migration.operations[0].state_forwards("grow", state)
        self.apps = state.apps
        self.Criteria = self.apps.get_model("grow", "Criteria")
        self.canonical = self.model_fixture_factory.create_genre("Rock")
        self.regional = self.model_fixture_factory.create_genre("Italian progressive rock")
        self.Criteria.objects.filter(pk=self.regional.pk).update(allows_multiple_primary_parents=True)

    def _values(self, field):
        return [
            self.Criteria.objects.values_list(field, flat=True).get(pk=c.pk) for c in (self.canonical, self.regional)
        ]

    def test_flag_maps_to_tree_name_and_back(self):
        migration_module.flag_to_tree_name(self.apps, None)
        assert self._values("tree_name") == ["canonical", "regional"]

        self.Criteria.objects.update(allows_multiple_primary_parents=False)
        migration_module.tree_name_to_flag(self.apps, None)
        assert self._values("allows_multiple_primary_parents") == [False, True]
