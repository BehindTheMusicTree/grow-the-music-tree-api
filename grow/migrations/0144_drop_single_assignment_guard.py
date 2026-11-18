"""Drop grow's own one-node-per-track guard: the genre kit enforces it with UNIQUE(dataset_id, track_id)."""

from importlib import import_module

from django.db import migrations

BOUNDARY = import_module("grow.migrations.0140_song_membership_boundary")
ATTRIBUTION = BOUNDARY.ATTRIBUTION


def drop_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(f"DROP TRIGGER IF EXISTS grow_single_assignment_guard ON {ATTRIBUTION}")
        schema_editor.execute("DROP FUNCTION IF EXISTS grow_single_assignment_guard()")
    else:
        for event in ("insert", "update"):
            schema_editor.execute(f"DROP TRIGGER IF EXISTS grow_single_assignment_{event}")


def restore_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        statements = list(BOUNDARY.postgres_statements())[-2:]
    else:
        statements = list(BOUNDARY.sqlite_statements())[-2:]
    for statement in statements:
        schema_editor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0143_song_genre_triggers_null_flag"),
        ("the_music_tree_genre_kit", "0022_attribution_dataset_unique"),
    ]
    operations = [migrations.RunPython(drop_guard, restore_guard)]
