import django.db.models.deletion
from django.db import migrations, models
from the_music_tree_api_kit.field import AppCharField
from the_music_tree_api_kit.field.foreign_key.AppForeignKey import AppForeignKey
from the_music_tree_api_kit.field.foreign_key.PrivateForeignKey import PrivateForeignKey
from the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField import PrivateOneToOneField


def copy_playlists_to_genre_kit(apps, schema_editor):
    Playlist = apps.get_model("grow", "Playlist")
    KitPlaylist = apps.get_model("the_music_tree_genre_kit", "Playlist")

    for playlist in Playlist.objects.all().iterator():
        KitPlaylist.objects.get_or_create(
            uuid=playlist.uuid,
            defaults=dict(
                created_on=playlist.created_on,
                updated_on=playlist.updated_on,
                user_id=playlist.user_id,
                play_count=playlist.play_count,
            ),
        )


def noop_reverse(apps, schema_editor):
    pass


def repoint_playlist_parent_links(apps, schema_editor):
    """
    Repoints `CriteriaPlaylist.playlist`/`ManualPlaylist.playlist` from `grow_playlist` to the
    kit's `the_music_tree_genre_kit_playlist` at the database level, driving
    `schema_editor.alter_field` directly with the live model classes instead of a declarative
    `AlterField` operation. See `0006_move_track_to_genre_kit.py`'s
    `repoint_track_parent_link` for why a plain `AlterField` can't express this MTI base change.
    """
    from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
    from grow.model.playlist.children.manual.ManualPlaylist import ManualPlaylist

    GrowPlaylist = apps.get_model("grow", "Playlist")

    for model_class in (CriteriaPlaylist, ManualPlaylist):
        new_field = model_class._meta.get_field("playlist")
        related_name = new_field.remote_field.related_name

        old_field = PrivateOneToOneField(
            GrowPlaylist,
            on_delete=django.db.models.deletion.CASCADE,
            parent_link=True,
            primary_key=True,
            related_name=related_name,
        )
        old_field.set_attributes_from_name("playlist")
        old_field.model = model_class

        schema_editor.alter_field(model_class, old_field, new_field)


def noop_reverse_schema(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    """
    Additive half of the Playlist-to-genre-kit move: copies every `grow_playlist` row into the
    kit's `the_music_tree_genre_kit_playlist` table under the same PK, then re-points
    `CriteriaPlaylist`/`ManualPlaylist`'s MTI parent links and `TrackPlaylistRel.playlist` at the
    kit's table. `grow_playlist` itself is left physically intact here on purpose -- dropping it is
    a separate, later migration -- so a bad deploy can be halted after this step runs without a
    destructive rollback.
    """

    dependencies = [
        ("grow", "0007_delete_grow_track"),
        ("grow", "0008_rename_legacy_playlist_index"),
        ("the_music_tree_genre_kit", "0004_playlist"),
    ]

    operations = [
        migrations.RunPython(copy_playlists_to_genre_kit, noop_reverse),
        migrations.AlterField(
            model_name="trackplaylistrel",
            name="playlist",
            field=PrivateForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="track_playlist_rels",
                to="the_music_tree_genre_kit.playlist",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(repoint_playlist_parent_links, noop_reverse_schema),
            ],
            state_operations=[
                migrations.DeleteModel(name="GenrePlaylist"),
                migrations.DeleteModel(name="TagPlaylist"),
                migrations.DeleteModel(name="CriteriaPlaylist"),
                migrations.DeleteModel(name="ManualPlaylist"),
                migrations.CreateModel(
                    name="CriteriaPlaylist",
                    fields=[
                        (
                            "playlist",
                            PrivateOneToOneField(
                                on_delete=django.db.models.deletion.CASCADE,
                                parent_link=True,
                                primary_key=True,
                                related_name="criteria_playlist",
                                serialize=False,
                                to="the_music_tree_genre_kit.playlist",
                            ),
                        ),
                        (
                            "criteria",
                            PrivateOneToOneField(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="criteria_playlist",
                                to="grow.criteria",
                            ),
                        ),
                        (
                            "parent",
                            PrivateForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="children",
                                to="grow.criteriaplaylist",
                            ),
                        ),
                        (
                            "root",
                            PrivateForeignKey(
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                related_name="root_descendants",
                                to="grow.criteriaplaylist",
                            ),
                        ),
                        (
                            "type",
                            AppForeignKey(
                                on_delete=django.db.models.deletion.CASCADE, to="the_music_tree_genre_kit.criteriatype"
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "Criteria Playlist",
                        "verbose_name_plural": "Criteria Playlists",
                        "db_table": "grow_criteria_playlist",
                        "indexes": [models.Index(fields=["criteria"], name="crit_playlist_criteria_idx")],
                    },
                    bases=("the_music_tree_genre_kit.playlist",),
                ),
                migrations.CreateModel(
                    name="ManualPlaylist",
                    fields=[
                        (
                            "playlist",
                            PrivateOneToOneField(
                                on_delete=django.db.models.deletion.CASCADE,
                                parent_link=True,
                                primary_key=True,
                                related_name="manual_playlist",
                                serialize=False,
                                to="the_music_tree_genre_kit.playlist",
                            ),
                        ),
                        (
                            "_name",
                            AppCharField(db_column="name", max_length=256),
                        ),
                    ],
                    options={
                        "verbose_name": "Manual Playlist",
                        "verbose_name_plural": "Manual Playlists",
                        "db_table": "grow_manual_playlist",
                        "indexes": [models.Index(fields=["_name"], name="manual_playlist_name_idx")],
                        "constraints": [
                            models.CheckConstraint(
                                condition=models.Q(("_name", ""), _negated=True), name="manual_playlist_non_empty_name"
                            )
                        ],
                    },
                    bases=("the_music_tree_genre_kit.playlist",),
                ),
                migrations.CreateModel(
                    name="GenrePlaylist",
                    fields=[],
                    options={
                        "db_table": "grow_genre_playlist",
                        "proxy": True,
                        "indexes": [],
                        "constraints": [],
                    },
                    bases=("grow.criteriaplaylist",),
                ),
                migrations.CreateModel(
                    name="TagPlaylist",
                    fields=[],
                    options={
                        "db_table": "grow_tag_playlist",
                        "proxy": True,
                        "indexes": [],
                        "constraints": [],
                    },
                    bases=("grow.criteriaplaylist",),
                ),
            ],
        ),
    ]
