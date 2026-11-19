import importlib

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from tests.utils.AppTestCase import AppTestCase

migration = importlib.import_module("grow.migrations.0148_regional_overview_types_data")


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.apps = MigrationLoader(connection).project_state(("grow", "0147_regional_graph_decision_lists")).apps
        self.entries = self.apps.get_model("grow", "CurationEntry").objects

    def _old(self, key: str, reason: str):
        return self.entries.create(
            user=None, list_name=migration.OLD, key=key, values={"status": "historical"}, reason=reason
        )

    def test_forwards_then_list_renamed_and_provenance_added(self):
        self._old("Q1", "kept")
        self._old("Q2", "")

        migration.forwards(self.apps, None)

        assert not self.entries.filter(list_name=migration.OLD).exists()
        kept = self.entries.get(list_name=migration.NEW, key="Q1")
        assert kept.values == {
            "overview_type": "historical",
            "decision_id": "legacy-overview-status:Q1",
            "decision_source": migration.LEGACY_SOURCE,
        }
        assert kept.reason == "kept"
        assert self.entries.get(list_name=migration.NEW, key="Q2").reason == migration.LEGACY_REASON

    def test_backwards_then_original_shape_restored(self):
        self._old("Q1", "kept")
        self._old("Q2", "")
        migration.forwards(self.apps, None)

        migration.backwards(self.apps, None)

        assert not self.entries.filter(list_name=migration.NEW).exists()
        assert self.entries.get(list_name=migration.OLD, key="Q1").values == {"status": "historical"}
        assert self.entries.get(list_name=migration.OLD, key="Q2").reason == ""
