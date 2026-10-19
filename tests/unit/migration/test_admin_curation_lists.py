from importlib import import_module

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from grow.model.curation.CurationEntry import CurationEntry
from tests.utils.AppTestCase import AppTestCase

migration_module = import_module("grow.migrations.0058_admin_curation_lists")


class TestCase(AppTestCase):
    def test_regional_secondary_parents_then_secondary_parents_add(self):
        apps = MigrationLoader(connection).project_state(("grow", "0057_curation_review_item")).apps
        values = {"item_label": "x", "parent_label": "Rock"}
        apps.get_model("grow", "CurationEntry").objects.create(
            user=None, list_name="regional_secondary_parents", key="Q1\tQ2", values=values, reason="r"
        )

        migration_module.move_to_secondary_parents(apps, None)

        entry = CurationEntry.objects.get(key="Q1\tQ2")
        assert entry.list_name == "secondary_parents"
        assert entry.values == {**values, "action": "add"}
