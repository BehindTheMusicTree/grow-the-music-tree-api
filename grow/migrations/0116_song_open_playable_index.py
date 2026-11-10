from django.db import migrations, models

from grow.model.song.playable import OPEN_PLAYABLE

INDEX = "grow_song_open_playable_idx"


def _index() -> models.Index:
    return models.Index(fields=["track"], name=INDEX, condition=OPEN_PLAYABLE)


def _forwards(apps, schema_editor):
    model = apps.get_model("grow", "Song")
    if schema_editor.connection.vendor != "postgresql":
        schema_editor.add_index(model, _index())
        return
    # grow_song is ~31M rows: a plain CREATE INDEX would block writes. CONCURRENTLY cannot run in a transaction, and an
    # interrupted build leaves an INVALID index that IF NOT EXISTS would keep, so drop it first.
    valid = schema_editor.connection.cursor()
    with valid:
        valid.execute("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(%s)", [INDEX])
        row = valid.fetchone()
    if row is not None and not row[0]:
        schema_editor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
    sql = str(_index().create_sql(model, schema_editor, concurrently=True))
    schema_editor.execute(sql.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1))


def _backwards(apps, schema_editor):
    model = apps.get_model("grow", "Song")
    if schema_editor.connection.vendor != "postgresql":
        schema_editor.remove_index(model, _index())
        return
    schema_editor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("grow", "0115_maintain_genre_catalogue_counts"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.AddIndex(model_name="song", index=_index())],
            database_operations=[migrations.RunPython(_forwards, _backwards)],
        ),
    ]
