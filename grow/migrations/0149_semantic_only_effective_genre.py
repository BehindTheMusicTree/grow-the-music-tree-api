"""Derive a song's effective genre from attributions only: drop the `Track.genre_id` fallback.

Without a `grow` dataset a song now has no genre. Canonical songs cannot be migrated without that dataset, so the
migration fails explicitly instead of nulling their genres; publish the dataset first. Reversible: the reverse
restores the fallback function and resyncs the column.
"""

from importlib import import_module

from django.db import migrations

BOUNDARY = import_module("grow.migrations.0140_song_membership_boundary")
DATASET, ATTRIBUTION, NODE, CRITERIA = BOUNDARY.DATASET, BOUNDARY.ATTRIBUTION, BOUNDARY.NODE, BOUNDARY.CRITERIA
SONG, TRACK = BOUNDARY.SONG, BOUNDARY.TRACK

SEMANTIC = f"""CREATE OR REPLACE FUNCTION grow_effective_genre(p_track uuid) RETURNS uuid AS $$
    SELECT c.uuid FROM {ATTRIBUTION} a
        JOIN {NODE} n ON n.id = a.node_id AND n.dataset_id = 'grow' AND n.is_active
        JOIN {CRITERIA} c ON c.graph_node_id = a.node_id WHERE a.track_id = p_track LIMIT 1 $$ LANGUAGE sql STABLE"""
LEGACY = f"""CREATE OR REPLACE FUNCTION grow_effective_genre(p_track uuid) RETURNS uuid AS $$
    SELECT {BOUNDARY.effective("p_track")} $$ LANGUAGE sql STABLE"""
RESYNC = f"""UPDATE {SONG} s SET genre_id = grow_effective_genre(s.track_id)
    WHERE s.genre_id IS DISTINCT FROM grow_effective_genre(s.track_id)"""


def _resync(schema_editor, function):
    schema_editor.execute("SELECT set_config('grow.membership_maintenance', 'on', true)")
    schema_editor.execute(function)
    schema_editor.execute(RESYNC)
    schema_editor.execute(f"ANALYZE {SONG}")


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT EXISTS (SELECT 1 FROM {DATASET} WHERE key = 'grow')")
        has_dataset = cursor.fetchone()[0]
        cursor.execute(
            f"SELECT EXISTS (SELECT 1 FROM {SONG} s JOIN {TRACK} t ON t.uuid = s.track_id WHERE t.user_id IS NULL)"
        )
        has_songs = cursor.fetchone()[0]
    if has_songs and not has_dataset:
        raise RuntimeError(
            "Publish the `grow` genre graph dataset before migrating: canonical songs would lose their genre"
        )
    _resync(schema_editor, SEMANTIC)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _resync(schema_editor, LEGACY)


class Migration(migrations.Migration):
    dependencies = [("grow", "0148_regional_overview_types_data")]
    operations = [migrations.RunPython(forwards, backwards)]
