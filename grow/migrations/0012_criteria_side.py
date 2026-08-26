from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0011_delete_grow_track_playlist_rel"),
    ]

    operations = [
        migrations.AddField(
            model_name="criteria",
            name="side",
            field=models.CharField(
                blank=True,
                choices=[("core", "Core"), ("pop", "Pop")],
                db_column="side",
                max_length=4,
                null=True,
            ),
        ),
    ]
