import uuid

from django.conf import settings
from django.db import migrations


def backfill_criterialess_playlists(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    # Historical CriteriaType pks, seeded by 0002_seed_criteria_types: 0 = genre, 1 = tag.
    CriteriaType = apps.get_model("the_music_tree_genre_kit", "CriteriaType")
    CriteriaPlaylist = apps.get_model("grow", "CriteriaPlaylist")

    criteria_types = list(CriteriaType.objects.filter(pk__in=[0, 1]))
    for user in User.objects.all():
        for criteria_type in criteria_types:
            if CriteriaPlaylist.objects.filter(user=user, type=criteria_type, criteria=None).exists():
                continue
            # Historical models bypass the real CriteriaPlaylist's save() hooks
            # (_set_uuid_if_necessary/_set_root), which normally assign the MTI
            # pk and self-reference `root` before insert. Reproduced explicitly here:
            # the child's pk (the `playlist` parent_link column) and the parent
            # Playlist row's `uuid` pk must be the same value, and `root` self-references.
            new_pk = uuid.uuid4()
            playlist = CriteriaPlaylist(user=user, type=criteria_type, criteria=None)
            playlist.pk = new_pk
            playlist.uuid = new_pk
            playlist.root_id = new_pk
            playlist.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0004_track_trackplaylistrel_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_criterialess_playlists, noop),
    ]
