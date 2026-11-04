from django.db import migrations

# The songs merge sets this transaction-local flag and applies the same per-playlist delta itself: the statement
# trigger's transition tables carry no statistics, which made it cost minutes per 100k updated songs.
FUNCTION = """
CREATE OR REPLACE FUNCTION views_count_song_update() RETURNS trigger AS $$
BEGIN
    {guard}
    UPDATE grow_criteria_playlist cp SET views_count = cp.views_count + d.v
    FROM (
        SELECT r.playlist_id,
            sum(coalesce(n.youtube_view_count, 0) - coalesce(o.youtube_view_count, 0)) AS v
        FROM new_rows n
        JOIN old_rows o ON o.track_id = n.track_id
        JOIN the_music_tree_genre_kit_track_playlist_rel r ON r.track_id = n.track_id
        WHERE n.youtube_view_count IS DISTINCT FROM o.youtube_view_count
        GROUP BY r.playlist_id
    ) d
    WHERE cp.playlist_id = d.playlist_id AND d.v <> 0;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

GUARD = """IF current_setting('grow.skip_views_count_song_update', true) = 'on' THEN
        RETURN NULL;
    END IF;"""


def _replace_function(guard: str):
    def run(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(FUNCTION.format(guard=guard))

    return run


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0090_region_map_tileset_index"),
    ]

    operations = [migrations.RunPython(_replace_function(GUARD), _replace_function(""))]
