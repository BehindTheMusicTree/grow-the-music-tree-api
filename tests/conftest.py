import unicodedata

import pytest
from django.db import connection
from django.db.backends.signals import connection_created

from tests.utils.restore_kit_seeded_data import restore_kit_seeded_data, snapshot_kit_seeded_data


def _grow_search_norm(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).lower()


def _register_search_norm(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        connection.connection.create_function("grow_search_norm", 1, _grow_search_norm, deterministic=True)


connection_created.connect(_register_search_norm)


@pytest.fixture(scope="session")
def migration_seed_snapshot(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        return snapshot_kit_seeded_data()


@pytest.fixture(autouse=True)
def restore_flushed_migration_seeds(request):
    """A transactional test flushes every table on teardown, migration seeds included: restore them first."""
    django_test_case = request.instance is not None and hasattr(request.instance, "_fixture_setup")
    marker = request.node.get_closest_marker("django_db")
    uses_db = django_test_case or marker is not None or {"db", "transactional_db"} & set(request.fixturenames)
    if not uses_db:
        return
    # Snapshot at the first database test, before any flush can have emptied the seeds.
    snapshot = request.getfixturevalue("migration_seed_snapshot")
    if django_test_case:
        return  # Django TestCase classes manage their own database state in setUp.
    transactional = "transactional_db" in request.fixturenames or (
        marker is not None and marker.kwargs.get("transaction", False)
    )
    if not transactional:
        return
    request.getfixturevalue("_django_db_helper")
    restore_kit_seeded_data(snapshot)


@pytest.fixture(scope="session", autouse=True)
def sqlite_flush_graph_guards(django_db_setup):
    if connection.vendor != "sqlite":
        yield
        return

    original = connection.ops.sql_flush

    def sql_flush(style, tables, **kwargs):
        with connection.cursor() as cursor:
            cursor.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")
            guards = cursor.fetchall()
        drops = [f"DROP TRIGGER {connection.ops.quote_name(name)}" for name, _ in guards]
        return drops + original(style, tables, **kwargs) + [sql for _, sql in guards]

    connection.ops.sql_flush = sql_flush
    try:
        yield
    finally:
        connection.ops.sql_flush = original
