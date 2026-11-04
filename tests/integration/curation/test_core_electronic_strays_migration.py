import importlib

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from tests.integration.criteria.GenreTestCase import GenreTestCase

MIGRATION = "0088_core_electronic_strays"
migration = importlib.import_module(f"grow.migrations.{MIGRATION}")


class TestCase(GenreTestCase):
    def setUp(self):
        super().setUp()
        self.apps = MigrationLoader(connection).project_state(("grow", MIGRATION)).apps
        factory = self.model_fixture_factory
        self.core = factory.create_genre("Core electronic", wikidata_id=migration.CORE)
        self.edm = factory.create_genre("EDM", wikidata_id=migration.EDM, parent=self.core)
        self.underground = factory.create_genre(
            "Underground electronic", wikidata_id=migration.UNDERGROUND, parent=self.core
        )
        self.techno = factory.create_genre("Techno", wikidata_id="Q170611", parent=self.core)
        self.house = factory.create_genre("House music", wikidata_id="Q20502", parent=self.core)
        self.tech_house = factory.create_genre("Tech house", wikidata_id="Q598593", parent=self.core)
        self.other = factory.create_genre("Elsewhere", wikidata_id="Q1")
        self.untouched = factory.create_genre("Breakbeat", wikidata_id="Q663519", parent=self.other)
        # The historical model: the live manager snapshots rows of `CURATION_LISTS`, which dropped `main_parent`.
        self.apps.get_model("grow", "CurationEntry").objects.create(
            user=None,
            list_name="main_parent",
            key="Q598593",
            values={"parent_item_id": migration.CORE, "exclude_other_parents": True},
            reason="stray",
        )

    def _parent_of(self, genre: Genre) -> str | None:
        genre.refresh_from_db()
        return Genre.objects.get(pk=genre.parent_id).wikidata_id if genre.parent_id else None

    def test_strays_moved_under_their_scene_and_stray_rule_dropped(self):
        migration.reparent(self.apps, None)

        assert self._parent_of(self.techno) == migration.UNDERGROUND
        assert self._parent_of(self.house) == migration.EDM
        assert self._parent_of(self.tech_house) == "Q20502"
        rules = CurationEntry.objects.filter(user=None, list_name="main_parent")
        assert rules.get(key="Q170611").values["parent_item_id"] == migration.UNDERGROUND
        assert not rules.filter(key="Q598593").exists()

    def test_genre_outside_core_electronic_left_alone(self):
        migration.reparent(self.apps, None)

        assert self._parent_of(self.untouched) == "Q1"
