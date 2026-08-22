from django.db import migrations


def copy_track_playlist_rels_to_genre_kit(apps, schema_editor):
    TrackPlaylistRel = apps.get_model("grow", "TrackPlaylistRel")
    KitTrackPlaylistRel = apps.get_model("the_music_tree_genre_kit", "TrackPlaylistRel")

    for rel in TrackPlaylistRel.objects.all().iterator():
        KitTrackPlaylistRel.objects.get_or_create(
            user_id=rel.user_id,
            playlist_id=rel.playlist_id,
            track_id=rel.track_id,
            defaults=dict(
                created_on=rel.created_on,
                updated_on=rel.updated_on,
                position=rel.position,
            ),
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    """
    Additive half of the TrackPlaylistRel-to-genre-kit move: copies every `grow_track_playlist_rel`
    row into the kit's `the_music_tree_genre_kit_track_playlist_rel` table. `grow_track_playlist_rel`
    itself is left physically intact here on purpose -- dropping it is a separate, later migration --
    so a bad deploy can be halted after this step runs without a destructive rollback.
    """

    dependencies = [
        ("grow", "0009_delete_grow_playlist"),
        ("the_music_tree_genre_kit", "0005_trackplaylistrel_track_playlists_and_more"),
    ]

    operations = [
        migrations.RunPython(copy_track_playlist_rels_to_genre_kit, noop_reverse),
    ]
