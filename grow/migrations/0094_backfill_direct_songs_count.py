from django.db import migrations


def backfill(apps, schema_editor):
    from grow.track.direct_songs_count import recount_direct_songs_count_holding_writers

    recount_direct_songs_count_holding_writers(
        apps.get_model("grow", "Song"), apps.get_model("grow", "CriteriaPlaylist"), schema_editor.connection
    )


class Migration(migrations.Migration):
    # Its own migration so 0093's ACCESS EXCLUSIVE lock from AddField is released before the ~31M-song count.
    dependencies = [
        ("grow", "0093_playlist_direct_songs_count"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
