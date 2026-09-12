import os

from django.db import migrations


def delete_prototype_user(apps, schema_editor):
    User = apps.get_model("auth", "User")
    username = os.getenv("PROTOTYPE_USERNAME", "prototype")

    User.objects.filter(username=username).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0018_genre_essential_tracks"),
    ]

    operations = [
        migrations.RunPython(delete_prototype_user, noop),
    ]
