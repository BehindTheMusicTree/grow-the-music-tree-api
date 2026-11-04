from django.db import migrations


def backfill(apps, schema_editor):
    from grow.track.direct_songs_count import recount_direct_songs_count

    if schema_editor.connection.vendor == "postgresql":
        # Holds off writers (an import merge's delta would be overwritten by this older count) but not readers:
        # the tree keeps serving while the songs are counted.
        schema_editor.execute("LOCK TABLE grow_criteria_playlist IN SHARE ROW EXCLUSIVE MODE")
    recount_direct_songs_count(apps.get_model("grow", "Song"), apps.get_model("grow", "CriteriaPlaylist"))


class Migration(migrations.Migration):
    # Its own migration so 0093's ACCESS EXCLUSIVE lock from AddField is released before the ~31M-song count.
    dependencies = [
        ("grow", "0093_playlist_direct_songs_count"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
