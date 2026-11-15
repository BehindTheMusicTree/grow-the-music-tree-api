from django.db import migrations
from django.db.models import Count


def backfill(apps, schema_editor):
    song_model = apps.get_model("grow", "Song")
    playlist_model = apps.get_model("grow", "CriteriaPlaylist")
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("LOCK TABLE grow_criteria_playlist IN SHARE ROW EXCLUSIVE MODE")
    counts = dict(song_model.objects.filter(user__isnull=True).order_by().values_list("genre").annotate(n=Count("pk")))
    playlists = list(playlist_model.objects.filter(user__isnull=True, type_id=0))
    for playlist in playlists:
        playlist.direct_songs_count = counts.get(playlist.criteria_id, 0)
    playlist_model.objects.bulk_update(playlists, ["direct_songs_count"], batch_size=500)


class Migration(migrations.Migration):
    # Its own migration so 0093's ACCESS EXCLUSIVE lock from AddField is released before the ~31M-song count.
    dependencies = [
        ("grow", "0093_playlist_direct_songs_count"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
