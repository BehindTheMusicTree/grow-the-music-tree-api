import django.db.models.deletion
import the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0049_pipeline_run_request_origin"),
        ("the_music_tree_genre_kit", "0011_remove_track_user_title_index"),
    ]

    operations = [
        migrations.RenameModel("YoutubeTrack", "Recording"),
        migrations.AlterModelTable("recording", "grow_recording"),
        migrations.AlterModelOptions(
            name="recording",
            options={"verbose_name": "Recording", "verbose_name_plural": "Recordings"},
        ),
        migrations.AlterField(
            model_name="recording",
            name="track",
            field=the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField.PrivateOneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                parent_link=True,
                primary_key=True,
                related_name="recording",
                serialize=False,
                to="the_music_tree_genre_kit.track",
            ),
        ),
    ]
