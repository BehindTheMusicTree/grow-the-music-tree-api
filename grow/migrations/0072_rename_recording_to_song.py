import django.db.models.deletion
import the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField
from django.db import migrations, models

LIST_RENAMES = {"recording_genre": "song_genre", "essential_tracks": "essential_songs"}


def _rename_lists(apps, renames: dict[str, str]) -> None:
    for model in ("CurationEntry", "CurationReviewItem"):
        for old, new in renames.items():
            apps.get_model("grow", model).objects.filter(list_name=old).update(list_name=new)


def rename_lists_forward(apps, schema_editor):
    _rename_lists(apps, LIST_RENAMES)


def rename_lists_backward(apps, schema_editor):
    _rename_lists(apps, {new: old for old, new in LIST_RENAMES.items()})


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0071_geohistory_curation_lists"),
        ("the_music_tree_genre_kit", "0012_track_genre_uuid_index"),
    ]

    operations = [
        migrations.RenameModel("Recording", "Song"),
        migrations.AlterModelTable("song", "grow_song"),
        migrations.RenameField("genre", "essential_tracks", "essential_songs"),
        migrations.AlterModelOptions(
            name="song",
            options={"verbose_name": "Song", "verbose_name_plural": "Songs"},
        ),
        migrations.AlterField(
            model_name="curationentry",
            name="list_name",
            field=models.CharField(
                choices=[
                    ("accepted_canonical_roots", "accepted_canonical_roots"),
                    ("canonical_parent_additions", "canonical_parent_additions"),
                    ("capitalized_words", "capitalized_words"),
                    ("duplicate_genres", "duplicate_genres"),
                    ("indigenous_to_exclusions", "indigenous_to_exclusions"),
                    ("label_overrides", "label_overrides"),
                    ("main_parent", "main_parent"),
                    ("out_of_scope_genres", "out_of_scope_genres"),
                    ("overview_reclassifications", "overview_reclassifications"),
                    ("regional_overrides", "regional_overrides"),
                    ("regional_overview_additions", "regional_overview_additions"),
                    ("technique_genres", "technique_genres"),
                    ("theme_genres", "theme_genres"),
                    ("non_stylistic_genres", "non_stylistic_genres"),
                    ("umbrella_genres", "umbrella_genres"),
                    ("accepted_non_genre_tags", "accepted_non_genre_tags"),
                    ("canonical_genre_pop_side", "canonical_genre_pop_side"),
                    ("genre_alias", "genre_alias"),
                    ("secondary_parents", "secondary_parents"),
                    ("song_genre", "song_genre"),
                    ("recording_youtube_video", "recording_youtube_video"),
                    ("essential_songs", "essential_songs"),
                    ("summary_overrides", "summary_overrides"),
                    ("genre_precedence", "genre_precedence"),
                    ("entity_exclusions", "entity_exclusions"),
                    ("entity_membership_overrides", "entity_membership_overrides"),
                    ("entity_time_span_overrides", "entity_time_span_overrides"),
                ],
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="curationreviewitem",
            name="list_name",
            field=models.CharField(
                choices=[
                    ("accepted_canonical_roots", "accepted_canonical_roots"),
                    ("canonical_parent_additions", "canonical_parent_additions"),
                    ("capitalized_words", "capitalized_words"),
                    ("duplicate_genres", "duplicate_genres"),
                    ("indigenous_to_exclusions", "indigenous_to_exclusions"),
                    ("label_overrides", "label_overrides"),
                    ("main_parent", "main_parent"),
                    ("out_of_scope_genres", "out_of_scope_genres"),
                    ("overview_reclassifications", "overview_reclassifications"),
                    ("regional_overrides", "regional_overrides"),
                    ("regional_overview_additions", "regional_overview_additions"),
                    ("technique_genres", "technique_genres"),
                    ("theme_genres", "theme_genres"),
                    ("non_stylistic_genres", "non_stylistic_genres"),
                    ("umbrella_genres", "umbrella_genres"),
                    ("accepted_non_genre_tags", "accepted_non_genre_tags"),
                    ("canonical_genre_pop_side", "canonical_genre_pop_side"),
                    ("genre_alias", "genre_alias"),
                    ("secondary_parents", "secondary_parents"),
                    ("song_genre", "song_genre"),
                    ("recording_youtube_video", "recording_youtube_video"),
                    ("essential_songs", "essential_songs"),
                    ("summary_overrides", "summary_overrides"),
                    ("genre_precedence", "genre_precedence"),
                    ("entity_exclusions", "entity_exclusions"),
                    ("entity_membership_overrides", "entity_membership_overrides"),
                    ("entity_time_span_overrides", "entity_time_span_overrides"),
                ],
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="song",
            name="track",
            field=the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField.PrivateOneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                parent_link=True,
                primary_key=True,
                related_name="song",
                serialize=False,
                to="the_music_tree_genre_kit.track",
            ),
        ),
        migrations.RunPython(rename_lists_forward, rename_lists_backward),
    ]
