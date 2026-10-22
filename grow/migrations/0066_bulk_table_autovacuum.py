from django.db import migrations

TABLES = [
    "the_music_tree_genre_kit_track",
    "the_music_tree_genre_kit_track_artists",
    "grow_recording",
]

SETTINGS = (
    "autovacuum_vacuum_scale_factor",
    "autovacuum_vacuum_threshold",
    "autovacuum_analyze_scale_factor",
    "autovacuum_analyze_threshold",
    "autovacuum_vacuum_insert_scale_factor",
    "autovacuum_vacuum_insert_threshold",
)

# Absolute thresholds: at ~30M rows the default 20%/10% scale factors need millions of changed rows, which a
# nightly delta merge never reaches, so these tables were never vacuumed or analyzed.
SET_SQL = "ALTER TABLE {table} SET (" + ", ".join(
    f"{name} = {value}"
    for name, value in zip(SETTINGS, (0, 200000, 0, 100000, 0, 200000), strict=True)
) + ")"
RESET_SQL = "ALTER TABLE {table} RESET (" + ", ".join(SETTINGS) + ")"


def _set_autovacuum(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(SET_SQL.format(table=table))


def _reset_autovacuum(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(RESET_SQL.format(table=table))


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0065_curation_list_renames_and_precedence_qids"),
        ("the_music_tree_genre_kit", "0012_track_genre_uuid_index"),
    ]

    operations = [migrations.RunPython(_set_autovacuum, _reset_autovacuum)]
