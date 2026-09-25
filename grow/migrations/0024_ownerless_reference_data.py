import os
import uuid

from django.conf import settings
from django.db import migrations

APP_LABELS = ("grow", "the_music_tree_genre_kit")


def make_reference_data_ownerless(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    CriteriaType = apps.get_model("the_music_tree_genre_kit", "CriteriaType")
    CriteriaPlaylist = apps.get_model("grow", "CriteriaPlaylist")

    owned_models = [
        model
        for app_label in APP_LABELS
        for model in apps.get_app_config(app_label).get_models()
        if any(field.name == "user" for field in model._meta.local_fields)
    ]

    # 0003 created the system user with this username; its rows become the canonical dataset.
    system_user = User.objects.filter(username=os.getenv("SYSTEM_USERNAME") or "system").first()
    if system_user is not None:
        for model in owned_models:
            model.objects.filter(user=system_user).update(user=None)
        system_user.delete()

    # Every other user only ever received the criterialess playlists bootstrapped on creation.
    CriteriaPlaylist.objects.filter(user__isnull=False, criteria=None).delete()

    # Historical CriteriaType pks, seeded by 0002_seed_criteria_types: 0 = genre, 1 = tag.
    for criteria_type in CriteriaType.objects.filter(pk__in=[0, 1]):
        if CriteriaPlaylist.objects.filter(user=None, type=criteria_type, criteria=None).exists():
            continue
        # See 0005: historical models skip save() hooks that set the MTI pk and self-referencing root.
        new_pk = uuid.uuid4()
        playlist = CriteriaPlaylist(user=None, type=criteria_type, criteria=None)
        playlist.pk = new_pk
        playlist.uuid = new_pk
        playlist.root_id = new_pk
        playlist.save()


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0023_nullable_user"),
        ("the_music_tree_genre_kit", "0006_nullable_user"),
    ]

    operations = [
        migrations.RunPython(make_reference_data_ownerless, migrations.RunPython.noop),
    ]
