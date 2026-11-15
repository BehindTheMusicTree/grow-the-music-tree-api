import unicodedata

import pytest
from django.db import connection
from django.db.backends.signals import connection_created


def _grow_search_norm(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).lower()


def _register_search_norm(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        connection.connection.create_function("grow_search_norm", 1, _grow_search_norm, deterministic=True)


connection_created.connect(_register_search_norm)


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
