from django.db import migrations, models

from grow.model.song.playable import RESTRICTED_POLICY

INDEX = "grow_song_restricted_idx"


def _index() -> models.Index:
    return models.Index(
        fields=["track"], include=["youtube_region_restriction"], name=INDEX, condition=RESTRICTED_POLICY
    )


def _forwards(apps, schema_editor):
    model = apps.get_model("grow", "Song")
    if schema_editor.connection.vendor != "postgresql":
        schema_editor.add_index(model, _index())
        return
    # grow_song is ~32M rows: a plain CREATE INDEX would block writes. CONCURRENTLY cannot run in a transaction, and an
    # interrupted build leaves an INVALID index that IF NOT EXISTS would keep, so drop it first.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(%s)", [INDEX])
        row = cursor.fetchone()
    if row is not None and not row[0]:
        schema_editor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
    sql = str(_index().create_sql(model, schema_editor, concurrently=True))
    schema_editor.execute(sql.replace("CREATE INDEX CONCURRENTLY", "CREATE INDEX CONCURRENTLY IF NOT EXISTS", 1))


def _backwards(apps, schema_editor):
    model = apps.get_model("grow", "Song")
    if schema_editor.connection.vendor != "postgresql":
        schema_editor.remove_index(model, _index())
        return
    schema_editor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("grow", "0116_region_map_snapshot_hidden_regions_checksum"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.AddIndex(model_name="song", index=_index())],
            database_operations=[migrations.RunPython(_forwards, _backwards)],
        ),
    ]
