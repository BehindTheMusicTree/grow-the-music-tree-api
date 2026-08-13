import os

from django.contrib.auth.hashers import make_password
from django.core.management.base import CommandError
from django.db import migrations


def create_system_user(apps, schema_editor):
    User = apps.get_model("auth", "User")
    username = os.getenv("SYSTEM_USERNAME", None)

    if not username:
        raise CommandError("⚠️ SYSTEM_USERNAME must be set in environment variables before running migrations.")

    user, _created = User.objects.get_or_create(
        username=username,
        defaults={
            "is_active": True,
            "is_staff": False,
            "is_superuser": False,
        },
    )

    # enforce unusable password even if user already existed
    if user.password and not user.password.startswith("!"):
        user.password = make_password(None)
        user.save(update_fields=["password"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0002_seed_criteria_types"),
    ]

    operations = [
        migrations.RunPython(create_system_user, noop),
    ]
