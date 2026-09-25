from django.db import migrations, models
import django.db.models.functions.text


class Migration(migrations.Migration):

    dependencies = [
        ('grow', '0026_backfill_genre_source'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='criteria',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('_name'), condition=models.Q(('user__isnull', True)), name='unique_canonical_name'),
        ),
        migrations.AddConstraint(
            model_name='criteria',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('_name'), models.F('user'), condition=models.Q(('user__isnull', False)), name='unique_name_per_user'),
        ),
        migrations.AddConstraint(
            model_name='genre',
            constraint=models.UniqueConstraint(condition=models.Q(('user__isnull', True), ('wikidata_id__isnull', False)), fields=('wikidata_id',), name='unique_canonical_wikidata_id'),
        ),
        migrations.AddConstraint(
            model_name='genre',
            constraint=models.UniqueConstraint(condition=models.Q(('user__isnull', False), ('wikidata_id__isnull', False)), fields=('wikidata_id', 'user'), name='unique_wikidata_id_per_user'),
        ),
    ]
