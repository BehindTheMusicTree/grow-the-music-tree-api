from django.db import migrations, models


def flag_to_tree_name(apps, schema_editor):
    apps.get_model("grow", "Criteria").objects.filter(allows_multiple_primary_parents=True).update(tree_name="regional")


def tree_name_to_flag(apps, schema_editor):
    apps.get_model("grow", "Criteria").objects.filter(tree_name="regional").update(allows_multiple_primary_parents=True)


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0032_historyentry_actor"),
    ]

    operations = [
        migrations.AddField(
            model_name="criteria",
            name="tree_name",
            field=models.CharField(
                choices=[("canonical", "Canonical"), ("regional", "Regional")], default="canonical", max_length=16
            ),
        ),
        migrations.RunPython(flag_to_tree_name, tree_name_to_flag),
        migrations.RemoveField(
            model_name="criteria",
            name="allows_multiple_primary_parents",
        ),
    ]
