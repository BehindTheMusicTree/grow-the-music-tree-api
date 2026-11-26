from django.db import migrations, models


def _rename(apps, old, new):
    apps.get_model("grow", "Criteria").objects.filter(tree_name=old).update(tree_name=new)


def forward(apps, schema_editor):
    _rename(apps, "canonical", "global")


def backward(apps, schema_editor):
    _rename(apps, "global", "canonical")


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0167_review_item_genre_not_in_graph"),
    ]

    operations = [
        # Choices and a Python-side default only: no schema change, and rebuilding grow_criteria on SQLite
        # fails while the grow_graph_* triggers (migration 0132) reference it.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="criteria",
                    name="tree_name",
                    field=models.CharField(
                        choices=[("global", "Global"), ("regional", "Regional")], default="global", max_length=16
                    ),
                ),
            ]
        ),
        migrations.RunPython(forward, backward),
    ]
