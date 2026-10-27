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


def _add_folded_name(model_name, table, expression):
    field = models.GeneratedField(db_persist=True, expression=expression, output_field=models.TextField())

    def forward(apps, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            new_field = field.clone()
            new_field.set_attributes_from_name("folded_name")
            schema_editor.add_field(apps.get_model("grow", model_name), new_field)
            return
        schema_editor.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS folded_name text "
            'GENERATED ALWAYS AS (grow_search_norm("name")) STORED'
        )

    def backward(apps, schema_editor):
        schema_editor.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS folded_name")

    # Idempotent on PostgreSQL because this non-atomic migration can die after the column is added but before
    # it is recorded as applied, and AddField has no IF NOT EXISTS.
    return migrations.SeparateDatabaseAndState(
        state_operations=[migrations.AddField(model_name=model_name, name="folded_name", field=field)],
        database_operations=[migrations.RunPython(forward, backward)],
    )


class Migration(migrations.Migration):
    # Adding a stored generated column rewrites the table under an ACCESS EXCLUSIVE lock (about a minute on ~1.9M
    # artists): deploy outside an import run. The index swap runs outside a transaction to use CONCURRENTLY.
    atomic = False

    dependencies = [
        ("grow", "0074_artist_recording_count_all_songs"),
    ]

    operations = [
        _add_folded_name("artist", "grow_artist", Func(F("_name"), function="grow_search_norm")),
        _add_folded_name("artistalias", "grow_artist_alias", Func(F("name"), function="grow_search_norm")),
        migrations.RunPython(_swap_indexes, _restore_indexes),
    ]
