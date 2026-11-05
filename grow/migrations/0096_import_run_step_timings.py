from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0095_history_entry_content_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="importrun",
            name="step_timings",
            field=models.JSONField(null=True),
        ),
    ]
