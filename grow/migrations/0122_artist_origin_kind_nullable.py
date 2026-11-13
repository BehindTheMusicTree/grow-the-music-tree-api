from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grow', '0121_artist_origin'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='artist',
            name='artist_origin_complete',
        ),
        migrations.AddConstraint(
            model_name='artist',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('origin_name__isnull', False), ('origin_source__isnull', False)), models.Q(('origin_kind__isnull', True), ('origin_latitude__isnull', True), ('origin_longitude__isnull', True), ('origin_name__isnull', True), ('origin_region_id__isnull', True), ('origin_source__isnull', True), ('origin_wikidata_id__isnull', True)), _connector='OR'), name='artist_origin_complete'),
        ),
    ]
