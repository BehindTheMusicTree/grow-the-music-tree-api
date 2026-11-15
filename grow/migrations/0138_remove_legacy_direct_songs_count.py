from django.db import migrations


def remove_count(apps, schema_editor):
    # Native ALTER preserves SQLite triggers that reference this table.
    schema_editor.execute("ALTER TABLE grow_criteria_playlist DROP COLUMN direct_songs_count")


def restore_count(apps, schema_editor):
    schema_editor.execute("ALTER TABLE grow_criteria_playlist ADD COLUMN direct_songs_count bigint NOT NULL DEFAULT 0")
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("ALTER TABLE grow_criteria_playlist ALTER COLUMN direct_songs_count DROP DEFAULT")


class Migration(migrations.Migration):
    dependencies = [("grow", "0137_import_review_metadata_constraint")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(remove_count, restore_count)],
            state_operations=[migrations.RemoveField(model_name="criteriaplaylist", name="direct_songs_count")],
        ),
    ]
