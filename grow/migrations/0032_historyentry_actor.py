import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def map_actor_emails_to_users(apps, schema_editor):
    HistoryEntry = apps.get_model("grow", "HistoryEntry")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    emails = set(HistoryEntry.objects.exclude(actor_email=None).values_list("actor_email", flat=True))
    users = list(User.objects.filter(email__in=emails))
    users_by_email = {user.email: user for user in users}
    if len(users_by_email) != len(users):
        raise RuntimeError("Several Users share a history actor email; cannot map it to one actor")
    unmatched = emails - users_by_email.keys()
    if unmatched:
        raise RuntimeError(f"History actor emails with no matching User: {sorted(unmatched)}")
    for email, user in users_by_email.items():
        HistoryEntry.objects.filter(actor_email=email).update(actor=user)


def map_actors_to_emails(apps, schema_editor):
    HistoryEntry = apps.get_model("grow", "HistoryEntry")
    for entry in HistoryEntry.objects.exclude(actor=None).select_related("actor"):
        entry.actor_email = entry.actor.email
        entry.save(update_fields=["actor_email"])


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0031_userprofile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="historyentry",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="history_actions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(map_actor_emails_to_users, map_actors_to_emails),
        migrations.RemoveField(
            model_name="historyentry",
            name="actor_email",
        ),
    ]
