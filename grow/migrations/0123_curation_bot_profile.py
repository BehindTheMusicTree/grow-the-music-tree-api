from django.db import migrations

# Hard-coded: a migration must not depend on app code that can change later.
CURATION_BOT_USERNAME = "curation-bot"


def seed_curation_bot_profile(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("grow", "UserProfile")
    bot, _ = User.objects.get_or_create(username=CURATION_BOT_USERNAME)
    UserProfile.objects.get_or_create(user=bot, defaults={"pseudo": CURATION_BOT_USERNAME})


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("grow", "0122_artist_origin_kind_nullable"),
    ]

    operations = [
        migrations.RunPython(seed_curation_bot_profile, migrations.RunPython.noop),
    ]
