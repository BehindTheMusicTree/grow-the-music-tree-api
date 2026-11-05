import uuid

from django.db import migrations, models

TABLE = "grow_history_entry"
OLD_INDEX = "grow_histor_user_id_8cb111_idx"
NEW_INDEX = "grow_history_content_idx"


def _swap(schema_editor, create: str, columns: str, drop: str) -> None:
    concurrently = "CONCURRENTLY " if schema_editor.connection.vendor == "postgresql" else ""
    # A failed concurrent build leaves an INVALID index behind; dropping it first lets a retry rebuild it.
    schema_editor.execute(f"DROP INDEX {concurrently}IF EXISTS {create}")
    schema_editor.execute(f"CREATE INDEX {concurrently}{create} ON {TABLE} ({columns})")
    schema_editor.execute(f"DROP INDEX {concurrently}IF EXISTS {drop}")


def _forwards(apps, schema_editor):
    _swap(schema_editor, NEW_INDEX, "content_type_id, object_pk, created_on", OLD_INDEX)


def _backwards(apps, schema_editor):
    _swap(schema_editor, OLD_INDEX, "user_id, content_type_id, object_pk", NEW_INDEX)


class Migration(migrations.Migration):
    # CONCURRENTLY can't run in a transaction. It avoids locking history writes during deploy (~17M rows on staging).
    atomic = False

    dependencies = [
        ("grow", "0094_backfill_direct_songs_count"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(model_name="historyentry", name=OLD_INDEX),
                migrations.AddIndex(
                    model_name="historyentry",
                    index=models.Index(fields=["content_type", "content_uuid", "created_on"], name=NEW_INDEX),
                ),
                # A Python-side default: the column itself is unchanged.
                migrations.AlterField(
                    model_name="historyentry",
                    name="uuid",
                    field=models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False, unique=True
                    ),
                ),
            ],
            database_operations=[migrations.RunPython(_forwards, _backwards)],
        ),
    ]
