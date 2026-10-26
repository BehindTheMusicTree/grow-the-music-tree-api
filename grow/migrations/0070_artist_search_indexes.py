from django.db import migrations

INDEXES = {
    "grow_artist_name_trgm": "grow_artist",
    "grow_artist_alias_name_trgm": "grow_artist_alias",
}


def _create_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name, table in INDEXES.items():
        schema_editor.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} USING gin (grow_search_norm(name) gin_trgm_ops)"
        )


def _drop_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name in INDEXES:
        schema_editor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


class Migration(migrations.Migration):
    # CONCURRENTLY can't run in a transaction. It avoids locking writes to the ~1.87M-row artist table during deploy.
    atomic = False

    dependencies = [
        ("grow", "0069_artist_search_data"),
    ]

    operations = [
        migrations.RunPython(_create_indexes, _drop_indexes),
    ]
