from django.db import migrations

REL = "the_music_tree_genre_kit_track_playlist_rel"


def drop_unplayable_playlist_rels(apps, schema_editor):
    """Playlists hold playable recordings only (see TrackManager._is_playable): drop the rest, close the gaps."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""DELETE FROM {REL} WHERE track_id IN (
                SELECT track_id FROM grow_recording
                WHERE youtube_video_id IS NULL OR youtube_unplayable_reason IS NOT NULL
            )"""
        )
        # Renumbering every playlist only writes the rows whose position actually moved.
        cursor.execute(
            f"""UPDATE {REL} SET position = o.position FROM (
                SELECT id, row_number() OVER (PARTITION BY playlist_id ORDER BY position, id) AS position
                FROM {REL} WHERE position IS NOT NULL
            ) o WHERE {REL}.id = o.id AND {REL}.position <> o.position"""
        )


class Migration(migrations.Migration):
    dependencies = [("grow", "0050_rename_youtube_track_to_recording")]

    operations = [migrations.RunPython(drop_unplayable_playlist_rels, migrations.RunPython.noop)]
