"""Make the song genre fill and guard triggers fire on a connection that never set the maintenance flag.

`current_setting('grow.membership_maintenance', true)` is NULL until something in the session sets it, so
`NOT (flag = 'on')` was NULL and both triggers silently skipped on a fresh connection.
"""

from importlib import import_module

from django.db import migrations

BOUNDARY = import_module("grow.migrations.0140_song_membership_boundary")
SONG = BOUNDARY.SONG
OFF = "COALESCE(current_setting('grow.membership_maintenance', true), '') <> 'on'"


def redefine(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"""CREATE OR REPLACE FUNCTION grow_song_genre_fill() RETURNS trigger AS $$
        BEGIN
            IF {OFF} THEN NEW.genre_id := grow_effective_genre(NEW.track_id); END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
    schema_editor.execute(f"""CREATE OR REPLACE FUNCTION grow_song_genre_guard() RETURNS trigger AS $$
        BEGIN
            IF pg_trigger_depth() <= 1 AND {OFF} AND NEW.genre_id IS NOT NULL
               AND NEW.genre_id IS DISTINCT FROM grow_effective_genre(NEW.track_id) THEN
                RAISE EXCEPTION 'grow_song.genre_id is derived from the grow dataset and cannot be written directly'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql""")


class Migration(migrations.Migration):
    dependencies = [("grow", "0142_semantic_playlist_projection")]
    operations = [migrations.RunPython(redefine, migrations.RunPython.noop)]
