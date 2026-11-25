import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("grow", "0165_drop_alias_legacy_unmigrated")]
AFTER = [("grow", "0166_genre_alias_target_ids")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


class TestGenreAliasTargetIds(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_fills_the_known_aliases_and_keeps_targeted_ones(self):
        apps = migrate(BEFORE)
        entries = apps.get_model("grow", "CurationEntry").objects
        legacy = entries.create(
            list_name="genre_alias", key="aor", values={"wikidata_genre_name": "album-oriented rock"}
        )
        targeted = entries.create(
            list_name="genre_alias", key="other", values={"wikidata_genre_name": "X", "target_item_id": "Q9"}
        )

        apps = migrate(AFTER)

        entries = apps.get_model("grow", "CurationEntry").objects
        assert entries.get(pk=legacy.pk).values == {
            "wikidata_genre_name": "album-oriented rock",
            "target_item_id": "Q428656",
        }
        assert entries.get(pk=targeted.pk).values == targeted.values

    def test_refuses_an_unknown_alias_without_target(self):
        apps = migrate(BEFORE)
        entries = apps.get_model("grow", "CurationEntry").objects
        entries.create(list_name="genre_alias", key="mystery", values={"wikidata_genre_name": "Mystery"})

        try:
            with pytest.raises(RuntimeError, match="mystery"):
                migrate(AFTER)
        finally:
            entries.all().delete()
