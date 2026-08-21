import django.db.models.deletion
from django.db import migrations
from the_music_tree_api_kit.field import AppCharField
from the_music_tree_api_kit.field.foreign_key.PrivateForeignKey import PrivateForeignKey
from the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField import PrivateOneToOneField


def copy_tracks_to_genre_kit(apps, schema_editor):
    Track = apps.get_model("grow", "Track")
    KitTrack = apps.get_model("the_music_tree_genre_kit", "Track")

    for track in Track.objects.all().iterator():
        kit_track, created = KitTrack.objects.get_or_create(
            uuid=track.uuid,
            defaults=dict(
                created_on=track.created_on,
                updated_on=track.updated_on,
                user_id=track.user_id,
                play_count=track.play_count,
                title=track.title,
                track_number=track.track_number,
                rating=track.rating,
                language=track.language,
                archived=track.archived,
                album_id=track.album_id,
                genre_id=track.genre_id,
            ),
        )
        if created:
            kit_track.artists.set(track.artists.all())


def noop_reverse(apps, schema_editor):
    pass


def repoint_track_parent_link(apps, schema_editor):
    """
    Repoints `YoutubeTrack.track` from `grow_track` to the kit's `the_music_tree_genre_kit_track`
    at the database level, driving `schema_editor.alter_field` directly with the live model class
    instead of a declarative `AlterField` operation.

    A plain `AlterField` can't express this: `SeparateDatabaseAndState.database_operations` never
    sees the `bases=` change (only `state_operations` does), so its own state stream still
    declares `bases=('grow.track',)` for this model. Django's state renderer then finds no field
    satisfying that declared parent link and silently injects an implicit `track_ptr` column
    alongside our real one. Using the actual (already-correct) Python model class here sidesteps
    that state rendering path altogether.

    `UploadedTrack` never needs this treatment: it's dead code with no live data, so its table is
    dropped outright (see this migration's `database_operations`) instead of repointed.
    """
    from grow.model.youtube_track.YoutubeTrack import YoutubeTrack

    GrowTrack = apps.get_model("grow", "Track")

    new_field = YoutubeTrack._meta.get_field("track")
    related_name = new_field.remote_field.related_name

    old_field = PrivateOneToOneField(
        GrowTrack,
        on_delete=django.db.models.deletion.CASCADE,
        parent_link=True,
        primary_key=True,
        related_name=related_name,
    )
    old_field.set_attributes_from_name("track")
    old_field.model = YoutubeTrack

    schema_editor.alter_field(YoutubeTrack, old_field, new_field)


def noop_reverse_schema(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    """
    Additive half of the Track-to-genre-kit move: copies every `grow_track` row into the
    kit's `the_music_tree_genre_kit_track` table under the same PK, then re-points the
    `YoutubeTrack` MTI parent link and `TrackPlaylistRel.track` at the kit's table, and drops
    the dead `UploadedTrack` model/table outright. `grow_track` itself is left physically intact
    here on purpose -- dropping it is a separate, later migration -- so a bad deploy can be
    halted after this step runs without a destructive rollback.
    """

    dependencies = [
        ("grow", "0005_backfill_criterialess_playlists"),
        ("the_music_tree_genre_kit", "0003_track_user_and_indexes"),
    ]

    operations = [
        migrations.RunPython(copy_tracks_to_genre_kit, noop_reverse),
        migrations.AlterField(
            model_name="trackplaylistrel",
            name="track",
            field=PrivateForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="track_playlist_rels",
                to="the_music_tree_genre_kit.track",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.DeleteModel(name="UploadedTrack"),
                migrations.RunPython(repoint_track_parent_link, noop_reverse_schema),
            ],
            state_operations=[
                migrations.DeleteModel(name="UploadedTrack"),
                migrations.DeleteModel(name="YoutubeTrack"),
                migrations.CreateModel(
                    name="YoutubeTrack",
                    fields=[
                        (
                            "track",
                            PrivateOneToOneField(
                                on_delete=django.db.models.deletion.CASCADE,
                                parent_link=True,
                                primary_key=True,
                                related_name="youtubetrack",
                                serialize=False,
                                to="the_music_tree_genre_kit.track",
                            ),
                        ),
                        (
                            "youtube_video_id",
                            AppCharField(max_length=11, blank=True, default=None, null=True),
                        ),
                    ],
                    options={
                        "verbose_name": "Youtube Track",
                        "verbose_name_plural": "Youtube Tracks",
                        "db_table": "grow_youtube_track",
                    },
                    bases=("the_music_tree_genre_kit.track",),
                ),
            ],
        ),
    ]
