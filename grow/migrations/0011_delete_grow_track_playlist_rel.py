from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("grow", "0010_move_track_playlist_rel_to_genre_kit")]

    operations = [
        migrations.RemoveIndex(model_name="trackplaylistrel", name="grow_track__user_id_928b41_idx"),
        migrations.RemoveIndex(model_name="trackplaylistrel", name="grow_track__user_id_1b2d91_idx"),
        migrations.RemoveField(model_name="trackplaylistrel", name="playlist"),
        migrations.RemoveField(model_name="trackplaylistrel", name="track"),
        migrations.RemoveField(model_name="trackplaylistrel", name="user"),
        migrations.DeleteModel(name="TrackPlaylistRel"),
    ]
