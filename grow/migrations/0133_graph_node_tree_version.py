"""Invalidate genre-tree responses when permanent graph nodes change visibility."""

from importlib import import_module

from django.db import migrations

VERSION = import_module("grow.migrations.0039_genre_tree_version")
TABLE = "the_music_tree_genre_kit_genregraphnode"
TRACKED_TABLES = [*VERSION.TRACKED_TABLES, TABLE]


def install(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(VERSION._postgres_trigger(TABLE))
    elif vendor == "sqlite":
        for sql in VERSION._sqlite_triggers(TABLE):
            schema_editor.execute(sql)
    else:
        raise RuntimeError("Reference graphs require PostgreSQL or SQLite")


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(f"DROP TRIGGER bump_genre_tree_version ON {TABLE}")
    else:
        for operation in ("insert", "update", "delete"):
            schema_editor.execute(f"DROP TRIGGER bump_genre_tree_version_{TABLE}_{operation}")


class Migration(migrations.Migration):
    dependencies = [("grow", "0132_permanent_graph_bindings")]
    operations = [migrations.RunPython(install, uninstall)]
