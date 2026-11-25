import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("grow", "0154_adopt_admin_genres_as_local_nodes")]
AFTER = [("grow", "0155_retire_expression_styles")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


class TestRetireExpressionStyles(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migration_converts_only_expression_identities(self):
        apps = migrate(BEFORE)
        entries = apps.get_model("grow", "CurationEntry").objects
        values = {"label": "French dub", "kind": "expression", "decision_id": "d1", "decision_source": "gold"}
        expression = entries.create(list_name="local_identities", key="LOCAL:french-dub", values=values, reason="r")
        overview = entries.create(list_name="local_identities", key="LOCAL:french-music", values={"kind": "overview"})
        anchoring = entries.create(list_name="regional_anchorings", key="LOCAL:french-dub\tLOCAL:french-music")
        apps.get_model("grow", "CurationReviewItem").objects.create(
            list_name="expression_styles", key="Q1\tQ2", column="style_item_id", item_id="Q2", reason="not_in_tree"
        )

        apps = migrate(AFTER)

        entries = apps.get_model("grow", "CurationEntry").objects
        converted = entries.get(pk=expression.pk)
        assert converted.values == {**values, "kind": "genre"}
        assert converted.key == expression.key
        assert converted.reason == expression.reason
        assert entries.get(pk=overview.pk).values == overview.values
        assert entries.get(pk=anchoring.pk).key == anchoring.key
        assert not apps.get_model("grow", "CurationReviewItem").objects.filter(list_name="expression_styles").exists()

    def test_migration_refuses_existing_expression_styles_before_updating_identities(self):
        apps = migrate(BEFORE)
        entries = apps.get_model("grow", "CurationEntry").objects
        expression = entries.create(list_name="local_identities", key="LOCAL:french-dub", values={"kind": "expression"})
        style = entries.create(list_name="expression_styles", key="LOCAL:french-dub\tQ2")

        try:
            with pytest.raises(RuntimeError, match="Move every expression_styles entry"):
                migrate(AFTER)

            assert entries.get(pk=expression.pk).values["kind"] == "expression"
            assert entries.filter(pk=style.pk).exists()
        finally:
            entries.filter(pk=style.pk).delete()
