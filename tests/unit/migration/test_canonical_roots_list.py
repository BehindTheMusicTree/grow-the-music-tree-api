from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("grow", "0150_genre_merges_list")]
AFTER = [("grow", "0151_canonical_roots_list")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


class TestCase(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_forward_then_root_rules_become_entries(self):
        apps = migrate(BEFORE)
        apps.get_model("grow", "GenreEdgeRule").objects.create(
            relation="canonical_parent", item_id="Q1", parent_item_id=None, exclude_other_parents=True, reason="why"
        )

        apps = migrate(AFTER)

        entry = apps.get_model("grow", "CurationEntry").objects.get(list_name="canonical_roots")
        assert (entry.key, entry.reason) == ("Q1", "why")
        assert entry.values["decision_source"] == "curation-legacy"
        assert not apps.get_model("grow", "GenreEdgeRule").objects.filter(item_id="Q1").exists()

    def test_backward_then_entries_become_root_rules(self):
        apps = migrate(AFTER)
        apps.get_model("grow", "CurationEntry").objects.create(
            list_name="canonical_roots", key="Q2", values={}, reason="why"
        )

        apps = migrate(BEFORE)

        rule = apps.get_model("grow", "GenreEdgeRule").objects.get(item_id="Q2")
        assert (rule.relation, rule.parent_item_id, rule.exclude_other_parents) == ("canonical_parent", None, True)
        assert not apps.get_model("grow", "CurationEntry").objects.filter(list_name="canonical_roots").exists()
