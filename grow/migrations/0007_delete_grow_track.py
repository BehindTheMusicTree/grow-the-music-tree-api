from django.db import migrations


class Migration(migrations.Migration):
    """
    Destructive half of the Track-to-genre-kit move: drops grow's now-empty local `Track`
    model/table, superseded by the kit's `the_music_tree_genre_kit_track`. Kept as its own
    migration, applied only after 0006's data copy has been verified, so a bad deploy can be
    halted after 0006 without needing a destructive rollback.
    """

    dependencies = [
        ("grow", "0006_move_track_to_genre_kit"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="track", name="grow_track_user_id_9cd683_idx"),
        migrations.RemoveIndex(model_name="track", name="grow_track_user_id_ad54d6_idx"),
        migrations.RemoveIndex(model_name="track", name="grow_track_user_id_ef8908_idx"),
        migrations.RemoveField(model_name="track", name="album"),
        migrations.RemoveField(model_name="track", name="artists"),
        migrations.RemoveField(model_name="track", name="genre"),
        migrations.RemoveField(model_name="track", name="user"),
        migrations.RemoveField(model_name="track", name="playlists"),
        migrations.DeleteModel(name="Track"),
    ]
