from importlib import import_module

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from tests.utils.AppTestCase import AppTestCase

MIGRATION = "0100_forced_canonical_genres_list"
migration_module = import_module(f"grow.migrations.{MIGRATION}")
REGGAE = "Q9794"


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.apps = MigrationLoader(connection).project_state(("grow", MIGRATION)).apps
        self.entries = self.apps.get_model("grow", "CurationEntry").objects
        self.reviews = self.apps.get_model("grow", "CurationReviewItem").objects
        self.entries.filter(key=REGGAE).delete()

    def test_canonical_overrides_rules_and_reviews_then_forced_canonical_genres(self):
        self.entries.create(user=None, list_name="canonical_overrides", key=REGGAE, values={}, reason="r")
        self.reviews.create(
            list_name="canonical_overrides", key=REGGAE, column="item_id", item_id=REGGAE, reason="missing"
        )

        migration_module._rename(migration_module.OLD_LIST, migration_module.NEW_LIST)(self.apps, None)

        assert self.entries.get(key=REGGAE).list_name == "forced_canonical_genres"
        assert self.reviews.get(key=REGGAE).list_name == "forced_canonical_genres"
        assert not self.entries.filter(list_name="canonical_overrides").exists()
