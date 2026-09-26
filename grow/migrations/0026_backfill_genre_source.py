from django.db import migrations
from django.db.models import Q


def backfill_source(apps, schema_editor):
    Genre = apps.get_model('grow', 'Genre')
    Genre.objects.filter(is_manually_edited=True).update(source='admin')
    # Ownerless rows imported before Gold nodes carried an id have NULL wikidata_id; the kit's keyed
    # import adopts them by name, but only as pipeline rows.
    Genre.objects.filter(Q(user__isnull=True) | Q(wikidata_id__isnull=False), is_manually_edited=False).update(
        source='pipeline'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('grow', '0025_criteria_multi_parents_and_genre_source'),
    ]

    operations = [
        migrations.RunPython(backfill_source, migrations.RunPython.noop),
    ]
