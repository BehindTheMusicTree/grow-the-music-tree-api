from importlib import import_module

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.utils.AppTestCase import AppTestCase

migration_module = import_module("grow.migrations.0036_locked_genres_to_curation_entries")
REASON = "migrated grow admin lock"


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.apps = MigrationLoader(connection).project_state(("grow", "0036_locked_genres_to_curation_entries")).apps
        self.rock = self.model_fixture_factory.create_genre("Rock", wikidata_id="Q8880001")

    def _locked(self, name: str, wikidata_id: str | None, *actions: HistoryAction, **kwargs) -> Genre:
        genre = self.model_fixture_factory.create_genre(
            name, wikidata_id=wikidata_id, is_manually_edited=True, **kwargs
        )
        for action in actions:
            HistoryEntry.objects.record(genre, action=action, actor=self.admin)
        return genre

    def _migrate(self) -> None:
        migration_module.locked_genres_to_curation_entries(self.apps, None)

    def _rows(self, list_name: str) -> list[dict]:
        return [e.row for e in CurationEntry.objects.filter(list_name=list_name, key__startswith="Q888")]

    def test_history_trail_then_matching_rules(self):
        self._locked("Punk rock", "Q8880002", HistoryAction.RENAMED, HistoryAction.PARENT_CHANGED, parent=self.rock)
        self._locked("Pala", "Q8880003", HistoryAction.ROOT_ACCEPTED)
        excluded = self._locked("Nenia", "Q8880004", HistoryAction.EXCLUDED, is_excluded=True)

        self._migrate()

        assert self._rows("label_overrides") == [
            {"item_id": "Q8880002", "display_label": "Punk rock", "reason": REASON}
        ]
        assert self._rows("main_parent") == [
            {
                "item_id": "Q8880002",
                "item_label": "Punk rock",
                "reason": REASON,
                "parent_item_id": "Q8880001",
                "exclude_other_parents": True,
            }
        ]
        assert self._rows("accepted_canonical_roots") == [{"item_id": "Q8880003", "item_label": "Pala"}]
        assert self._rows("out_of_scope_genres") == [{"item_id": "Q8880004", "item_label": "Nenia", "reason": REASON}]
        assert Genre.objects.get(pk=excluded.pk).is_manually_edited

    def test_inexpressible_or_pipeline_only_edits_then_no_rule(self):
        self._locked("Local", None, HistoryAction.RENAMED)
        self._locked("Root now", "Q8880005", HistoryAction.PARENT_CHANGED)
        self._locked("Regional", "Q8880006", HistoryAction.PARENT_CHANGED, tree_name="regional", parent=self.rock)
        pipeline_renamed = self.model_fixture_factory.create_genre("Piped", wikidata_id="Q8880007")
        HistoryEntry.objects.record(pipeline_renamed, action=HistoryAction.RENAMED, actor=None)

        self._migrate()

        assert not CurationEntry.objects.filter(key__startswith="Q888").exists()

    def test_already_in_an_exclusive_list_then_left_alone(self):
        CurationEntry.objects.upsert("theme_genres", {"item_id": "Q8880004", "item_label": "Nenia", "reason": "x"})
        self._locked("Nenia", "Q8880004", HistoryAction.EXCLUDED, is_excluded=True)

        self._migrate()

        assert self._rows("out_of_scope_genres") == []

    def test_rerun_then_idempotent(self):
        self._locked("Punk rock", "Q8880002", HistoryAction.RENAMED)
        self._migrate()
        before = list(CurationEntry.objects.filter(key__startswith="Q888").values("uuid", "values", "updated_on"))

        self._migrate()

        assert (
            list(CurationEntry.objects.filter(key__startswith="Q888").values("uuid", "values", "updated_on")) == before
        )
