from importlib import import_module

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from tests.utils.AppTestCase import AppTestCase

MIGRATION = "0096_three_parent_axes_curation_lists"
migration_module = import_module(f"grow.migrations.{MIGRATION}")
NASHEED = "Q783874"
ISLAMIC_MUSIC = "Q1482325"


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.apps = MigrationLoader(connection).project_state(("grow", MIGRATION)).apps
        self.entries = self.apps.get_model("grow", "CurationEntry").objects
        self.reviews = self.apps.get_model("grow", "CurationReviewItem").objects
        self.entries.filter(key__in=(NASHEED, "Q888001", "Q888002")).delete()

    def _parent(self, item_id: str, parent_item_id: str) -> None:
        self.entries.create(
            user=None,
            list_name="main_parent",
            key=item_id,
            values={"parent_item_id": parent_item_id, "exclude_other_parents": True},
            reason="r",
        )

    def _review(self, list_name: str, key: str, column: str) -> None:
        self.reviews.create(list_name=list_name, key=key, column=column, item_id="Q1", reason="missing")

    def _migrate(self) -> None:
        migration_module.split_parent_lists(self.apps, None)

    def test_parent_rules_then_split_by_axis(self):
        self._parent(NASHEED, ISLAMIC_MUSIC)
        self._parent("Q888001", "Q888000")

        self._migrate()

        assert self.entries.get(key=NASHEED).list_name == "regional_genre_parent"
        assert self.entries.get(key="Q888001").list_name == "canonical_parent"
        assert not self.entries.filter(list_name="main_parent").exists()

    def test_frozen_regional_item_with_another_parent_then_canonical(self):
        self._parent(NASHEED, "Q888000")

        self._migrate()

        assert self.entries.get(key=NASHEED).list_name == "canonical_parent"

    def test_overview_rule_then_keyed_by_item_and_overview(self):
        self.entries.create(
            user=None,
            list_name="regional_overrides",
            key="Q888002",
            values={"overview_item_id": "Q888003", "exclude_other_parents": False},
            reason="r",
        )

        self._migrate()

        entry = self.entries.get(key__startswith="Q888002")
        assert (entry.list_name, entry.key) == ("regional_overviews", "Q888002\tQ888003")
        assert entry.values == {"exclude_other_parents": False}

    def test_review_items_then_follow_their_entry(self):
        self._parent(NASHEED, ISLAMIC_MUSIC)
        self.entries.create(
            user=None,
            list_name="regional_overrides",
            key="Q888002",
            values={"overview_item_id": "Q888003", "exclude_other_parents": False},
            reason="r",
        )
        self._review("main_parent", NASHEED, "parent_item_id")
        self._review("regional_overrides", "Q888002", "overview_item_id")
        self._review("regional_overrides", "Q888009", "item_id")

        self._migrate()

        assert sorted(self.reviews.values_list("list_name", "key")) == [
            ("regional_genre_parent", NASHEED),
            ("regional_overviews", "Q888002\tQ888003"),
        ]

    def test_reverse_then_old_lists_back(self):
        self._parent(NASHEED, ISLAMIC_MUSIC)
        self.entries.create(
            user=None,
            list_name="regional_overrides",
            key="Q888002",
            values={"overview_item_id": "Q888003", "exclude_other_parents": False},
            reason="r",
        )
        self._review("regional_overrides", "Q888002", "overview_item_id")
        self._migrate()

        migration_module.merge_parent_lists(self.apps, None)

        assert self.entries.get(key=NASHEED).list_name == "main_parent"
        entry = self.entries.get(key="Q888002")
        assert entry.list_name == "regional_overrides"
        assert entry.values == {"exclude_other_parents": False, "overview_item_id": "Q888003"}
        assert list(self.reviews.values_list("list_name", "key")) == [("regional_overrides", "Q888002")]
