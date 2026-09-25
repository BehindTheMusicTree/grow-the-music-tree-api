from django.db import migrations
from django.db.models import Exists, OuterRef


def backfill_source(apps, schema_editor):
    Genre = apps.get_model('grow', 'Genre')
    Genre.objects.filter(is_manually_edited=True).update(source='admin')
    Genre.objects.filter(is_manually_edited=False, wikidata_id__isnull=False).update(source='pipeline')


def delete_legacy_duplicate_genres(apps, schema_editor):
    """
    Ownerless genres from the pre-wikidata import (NULL wikidata_id) that collide case-insensitively
    with a current ownerless genre would violate 0027's Lower(name) constraint. They are deleted through
    the live manager's `_delete_stale_instances` so tracks, playlists and children get reparented the same
    way a pipeline stale-delete does; historical models carry none of that logic. Any other conflict is
    left for 0027 to fail on.
    """
    HistoricalGenre = apps.get_model('grow', 'Genre')
    current = HistoricalGenre.objects.filter(
        user__isnull=True, wikidata_id__isnull=False, _name__iexact=OuterRef('_name')
    )
    legacy = HistoricalGenre.objects.filter(
        Exists(current), user__isnull=True, wikidata_id__isnull=True, is_manually_edited=False
    )
    legacy_ids = list(legacy.values_list('pk', flat=True))
    if not legacy_ids:
        return
    legacy.update(source='pipeline')

    from grow.model.criteria.children.genre.Genre import Genre

    Genre.objects._delete_stale_instances(Genre.objects.filter(pk__in=legacy_ids))


class Migration(migrations.Migration):

    dependencies = [
        ('grow', '0025_criteria_multi_parents_and_genre_source'),
    ]

    operations = [
        migrations.RunPython(backfill_source, migrations.RunPython.noop),
        migrations.RunPython(delete_legacy_duplicate_genres, migrations.RunPython.noop),
    ]
