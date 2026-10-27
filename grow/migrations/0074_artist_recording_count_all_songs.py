from django.db import migrations

BACKFILL = """UPDATE grow_artist SET recording_count = (
    SELECT count(*) FROM the_music_tree_genre_kit_track_artists ta WHERE ta.artist_id = grow_artist.uuid
)"""


class Migration(migrations.Migration):

    dependencies = [
        ('grow', '0073_entity_additions_curation_list'),
    ]

    operations = [
        migrations.RunSQL(BACKFILL, reverse_sql=migrations.RunSQL.noop),
    ]
