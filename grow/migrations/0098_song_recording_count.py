from django.db import migrations, models

# The name Postgres gives the inline check of a PositiveIntegerField, so the schema matches a plain AddField.
CHECK = "grow_song_recording_count_check"


def _field() -> models.PositiveIntegerField:
    field = models.PositiveIntegerField(blank=True, null=True)
    field.set_attributes_from_name("recording_count")
    return field


def _forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        schema_editor.add_field(apps.get_model("grow", "Song"), _field())
        return
    # An inline CHECK would scan grow_song (~31M rows) under ACCESS EXCLUSIVE, blocking every song read. Each statement
    # commits on its own: the column and the NOT VALID check are catalog-only, and VALIDATE scans under
    # SHARE UPDATE EXCLUSIVE, which lets reads and writes through. Each step is idempotent, so a migrate interrupted
    # midway can simply be re-run.
    # The catalog-only steps still queue for ACCESS EXCLUSIVE: behind a long merge, every song read would queue behind
    # them, so they give up instead and the deploy is retried.
    schema_editor.execute("SET lock_timeout = '5s'")
    try:
        schema_editor.execute("ALTER TABLE grow_song ADD COLUMN IF NOT EXISTS recording_count integer NULL")
        schema_editor.execute(f"ALTER TABLE grow_song DROP CONSTRAINT IF EXISTS {CHECK}")
        schema_editor.execute(f"ALTER TABLE grow_song ADD CONSTRAINT {CHECK} CHECK (recording_count >= 0) NOT VALID")
    finally:
        schema_editor.execute("RESET lock_timeout")
    schema_editor.execute(f"ALTER TABLE grow_song VALIDATE CONSTRAINT {CHECK}")


def _backwards(apps, schema_editor):
    schema_editor.remove_field(apps.get_model("grow", "Song"), _field())


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("grow", "0097_three_parent_axes_curation_lists"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="song",
                    name="recording_count",
                    field=models.PositiveIntegerField(blank=True, null=True),
                ),
            ],
            database_operations=[migrations.RunPython(_forwards, _backwards)],
        ),
        # The staging table is unlogged and emptied after every run: a plain AddField is instant there.
        migrations.AddField(
            model_name="songimportstaging",
            name="recording_count",
            field=models.PositiveIntegerField(null=True),
        ),
    ]
