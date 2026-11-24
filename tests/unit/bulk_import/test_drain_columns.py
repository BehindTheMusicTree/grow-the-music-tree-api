import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from grow.management.commands.wait_for_import_drain import live_attempts


@pytest.mark.django_db
def test_drain_selects_only_pre_migration_columns():
    """The deploy drains before migrating: the query must not touch columns added by later migrations."""
    with CaptureQueriesContext(connection) as queries:
        live_attempts()
    assert queries.captured_queries
    for query in queries.captured_queries:
        assert "worker_absent_since" not in query["sql"]
