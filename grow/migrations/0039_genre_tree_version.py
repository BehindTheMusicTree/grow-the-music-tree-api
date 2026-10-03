import uuid

from django.db import migrations, models

# Every table CriteriaPlaylistSimpleSerializer reads for the genre tree; a write to any of them changes the tree.
TRACKED_TABLES = [
    "grow_criteria",
    "grow_criteria_additional_primary_parents",
    "grow_criteria_secondary_parents",
    "grow_criteria_playlist",
    "grow_genre",
    "grow_user_profile",
    "the_music_tree_genre_kit_criteriatype",
    "the_music_tree_genre_kit_playlist",
    "the_music_tree_genre_kit_track_playlist_rel",
]

POSTGRES_FUNCTION = """
CREATE OR REPLACE FUNCTION bump_genre_tree_version() RETURNS trigger AS $$
BEGIN
    UPDATE grow_genre_tree_version SET token = gen_random_uuid() WHERE id = 1;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


def _postgres_trigger(table: str) -> str:
    return (
        f"CREATE TRIGGER bump_genre_tree_version AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION bump_genre_tree_version();"
    )


def _sqlite_triggers(table: str) -> list[str]:
    # SQLite has no statement-level triggers nor TRUNCATE; row-level keeps the test suite honest.
    return [
        f"CREATE TRIGGER bump_genre_tree_version_{table}_{op.lower()} AFTER {op} ON {table} BEGIN "
        "UPDATE grow_genre_tree_version SET token = lower(hex(randomblob(16))) WHERE id = 1; END;"
        for op in ("INSERT", "UPDATE", "DELETE")
    ]


def create_triggers(apps, schema_editor):
    apps.get_model("grow", "GenreTreeVersion").objects.create(pk=1, token=uuid.uuid4())
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        statements = [POSTGRES_FUNCTION, *map(_postgres_trigger, TRACKED_TABLES)]
    elif vendor == "sqlite":
        statements = [sql for table in TRACKED_TABLES for sql in _sqlite_triggers(table)]
    else:
        raise NotImplementedError(f"No genre tree version triggers for {vendor}")
    for sql in statements:
        schema_editor.execute(sql)


def drop_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        for table in TRACKED_TABLES:
            schema_editor.execute(f"DROP TRIGGER IF EXISTS bump_genre_tree_version ON {table};")
        schema_editor.execute("DROP FUNCTION IF EXISTS bump_genre_tree_version();")
    elif vendor == "sqlite":
        for table in TRACKED_TABLES:
            for op in ("insert", "update", "delete"):
                schema_editor.execute(f"DROP TRIGGER IF EXISTS bump_genre_tree_version_{table}_{op};")


class Migration(migrations.Migration):

    dependencies = [
        ("grow", "0038_curation_sync_state"),
        ("the_music_tree_genre_kit", "0009_trackplaylistrel_uniq_track_playlist_rel"),
    ]

    operations = [
        migrations.CreateModel(
            name="GenreTreeVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.UUIDField()),
            ],
            options={
                "db_table": "grow_genre_tree_version",
            },
        ),
        migrations.RunPython(create_triggers, drop_triggers),
    ]
