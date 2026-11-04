from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grow', '0091_views_count_song_update_skip'),
    ]

    operations = [
        migrations.AddField(
            model_name='songimportstaging',
            name='genre_wikidata_id',
            field=models.TextField(null=True),
        ),
    ]
