import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0048_remove_criteriaplaylist_parent_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="pipelinerunrequest",
            name="trigger",
            field=models.TextField(choices=[("manual", "Manual"), ("scheduled", "Scheduled")], default="manual"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="pipelinerunrequest",
            name="requested_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
