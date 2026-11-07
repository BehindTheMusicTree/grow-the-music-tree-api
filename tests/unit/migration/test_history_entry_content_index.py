import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("grow", "0094_backfill_direct_songs_count")]
AFTER = [("grow", "0095_history_entry_content_index")]
OLD_INDEX = "grow_histor_user_id_8cb111_idx"
NEW_INDEX = "grow_history_content_idx"


def _index_columns() -> dict[str, list[str]]:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, "grow_history_entry")
    return {name: c["columns"] for name, c in constraints.items() if name in (OLD_INDEX, NEW_INDEX)}


class TestCase(TransactionTestCase):
    def tearDown(self):
        MigrationExecutor(connection).migrate(AFTER)
        super().tearDown()

    def test_swaps_the_user_index_for_the_content_index_and_back(self):
        MigrationExecutor(connection).migrate(BEFORE)
        assert _index_columns() == {OLD_INDEX: ["user_id", "content_type_id", "object_pk"]}

        MigrationExecutor(connection).migrate(AFTER)
        assert _index_columns() == {NEW_INDEX: ["content_type_id", "object_pk", "created_on"]}


@pytest.mark.postgres
class TestCasePostgres(TestCase):
    """Runs the `CONCURRENTLY` path, outside any transaction as the migration requires."""
