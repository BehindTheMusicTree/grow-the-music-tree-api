from django.db import migrations


def remove_count(apps, schema_editor):
    # Native ALTER preserves SQLite triggers that reference this table.
    schema_editor.execute("ALTER TABLE grow_criteria_playlist DROP COLUMN direct_songs_count")


def restore_count(apps, schema_editor):
    schema_editor.execute("ALTER TABLE grow_criteria_playlist ADD COLUMN direct_songs_count integer NOT NULL DEFAULT 0")
    # Rollback must restore usable counts for the preceding application's delta writers.
    schema_editor.execute("""
        WITH counts AS (
            SELECT t.genre_id, COUNT(*) AS n
            FROM grow_song s JOIN the_music_tree_genre_kit_track t ON t.uuid = s.track_id
            WHERE t.user_id IS NULL GROUP BY t.genre_id
        )
        UPDATE grow_criteria_playlist SET direct_songs_count = COALESCE((
            SELECT n FROM counts WHERE counts.genre_id = grow_criteria_playlist.criteria_id
                OR (counts.genre_id IS NULL AND grow_criteria_playlist.criteria_id IS NULL)
        ), 0)
        WHERE type_id = 0 AND playlist_id IN (
            SELECT uuid FROM the_music_tree_genre_kit_playlist WHERE user_id IS NULL
        )
    """)


class Migration(migrations.Migration):
    dependencies = [("grow", "0137_import_review_metadata_constraint")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(remove_count, restore_count)],
            state_operations=[migrations.RemoveField(model_name="criteriaplaylist", name="direct_songs_count")],
        ),
    ]
