from django.db import migrations, models
from django.db.models import F, Func

NEW_INDEXES = {
    "grow_artist_folded_name_trgm": "grow_artist",
    "grow_artist_alias_folded_name_trgm": "grow_artist_alias",
}
OLD_INDEXES = {
    "grow_artist_name_trgm": "grow_artist",
    "grow_artist_alias_name_trgm": "grow_artist_alias",
}


def _swap_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name, table in NEW_INDEXES.items():
        schema_editor.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} USING gin (folded_name gin_trgm_ops)"
        )
    for name in OLD_INDEXES:
        schema_editor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


def _restore_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name, table in OLD_INDEXES.items():
        schema_editor.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} USING gin (grow_search_norm(name) gin_trgm_ops)"
        )
    for name in NEW_INDEXES:
        schema_editor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


class Migration(migrations.Migration):
    # Adding a stored generated column rewrites the table under an ACCESS EXCLUSIVE lock (about a minute on ~1.9M
    # artists): deploy outside an import run. The index swap runs outside a transaction to use CONCURRENTLY.
    atomic = False

    dependencies = [
        ("grow", "0074_artist_recording_count_all_songs"),
    ]

    operations = [
        migrations.AddField(
            model_name="artist",
            name="folded_name",
            field=models.GeneratedField(
                db_persist=True,
                expression=Func(F("_name"), function="grow_search_norm"),
                output_field=models.TextField(),
            ),
        ),
        migrations.AddField(
            model_name="artistalias",
            name="folded_name",
            field=models.GeneratedField(
                db_persist=True,
                expression=Func(F("name"), function="grow_search_norm"),
                output_field=models.TextField(),
            ),
        ),
        migrations.RunPython(_swap_indexes, _restore_indexes),
    ]
