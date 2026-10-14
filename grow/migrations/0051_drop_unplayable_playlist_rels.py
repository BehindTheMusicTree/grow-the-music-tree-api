from django.db import migrations

REL = "the_music_tree_genre_kit_track_playlist_rel"
# Historical CriteriaType pk 0 = genre (0002_seed_criteria_types). Manual and tag playlists keep their entries.
GENRE_PLAYLISTS = "SELECT playlist_id FROM grow_criteria_playlist WHERE type_id = 0"


def drop_unplayable_playlist_rels(apps, schema_editor):
    """Genre playlists hold playable recordings only (see TrackManager._is_playable): drop the rest, close the gaps."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""DELETE FROM {REL} WHERE track_id IN (
                SELECT track_id FROM grow_recording
                WHERE youtube_video_id IS NULL OR youtube_unplayable_reason IS NOT NULL
            ) AND playlist_id IN ({GENRE_PLAYLISTS})"""
        )
        # Renumbering every genre playlist only writes the rows whose position actually moved.
        cursor.execute(
            f"""UPDATE {REL} SET position = o.position FROM (
                SELECT id, row_number() OVER (PARTITION BY playlist_id ORDER BY position, id) AS position
                FROM {REL} WHERE position IS NOT NULL AND playlist_id IN ({GENRE_PLAYLISTS})
            ) o WHERE {REL}.id = o.id AND {REL}.position <> o.position"""
        )


class Migration(migrations.Migration):
    dependencies = [("grow", "0050_rename_youtube_track_to_recording")]

    operations = [migrations.RunPython(drop_unplayable_playlist_rels, migrations.RunPython.noop)]
