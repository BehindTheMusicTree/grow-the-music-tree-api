import uuid

from django.db import migrations, models

# Every table CriteriaPlaylistSimpleSerializer reads for the genre tree; a write to any of them changes the tree.
TRACKED_TABLES = [
    "grow_criteria",
    "grow_criteria_additional_primary_parents",
    "grow_criteria_secondary_parents",
    "grow_criteria_playlist",
    "grow_genre",
    "the_music_tree_genre_kit_criteriatype",
    "the_music_tree_genre_kit_playlist",
    "the_music_tree_genre_kit_track_playlist_rel",
]

# Columns the tree reads, so play_count increments (UPDATE ... SET play_count only) don't bump the token.
UPDATE_COLUMNS = {
    "the_music_tree_genre_kit_playlist": ["uuid", "created_on", "updated_on", "user_id"],
}


def _update_event(table: str) -> str:
    columns = UPDATE_COLUMNS.get(table)
    return f"UPDATE OF {', '.join(columns)}" if columns else "UPDATE"


POSTGRES_FUNCTION = """
CREATE OR REPLACE FUNCTION bump_genre_tree_version() RETURNS trigger AS $$
BEGIN
    -- ponytail: single-row lock serializes every tracked write until its transaction commits, so a long
    -- import blocks other tree writers for its whole duration; move to per-tree rows or a sequence if that bites.
    UPDATE grow_genre_tree_version SET token = gen_random_uuid() WHERE id = 1;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


def _postgres_trigger(table: str) -> str:
    return (
        f"CREATE TRIGGER bump_genre_tree_version AFTER INSERT OR {_update_event(table)} OR DELETE OR TRUNCATE "
        f"ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION bump_genre_tree_version();"
    )


def _sqlite_triggers(table: str) -> list[str]:
    # SQLite has no statement-level triggers nor TRUNCATE; row-level keeps the test suite honest.
    return [
        f"CREATE TRIGGER bump_genre_tree_version_{table}_{name} AFTER {event} ON {table} BEGIN "
        "UPDATE grow_genre_tree_version SET token = lower(hex(randomblob(16))) WHERE id = 1; END;"
        for name, event in (("insert", "INSERT"), ("update", _update_event(table)), ("delete", "DELETE"))
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
