from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("grow", "0008_move_playlist_to_genre_kit")]

    operations = [
        migrations.RemoveIndex(model_name="playlist", name="grow_playlist_user_uuid_idx"),
        migrations.RemoveField(model_name="playlist", name="user"),
        migrations.DeleteModel(name="Playlist"),
    ]
