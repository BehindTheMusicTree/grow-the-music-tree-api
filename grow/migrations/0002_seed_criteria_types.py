from django.db import migrations


def seed_criteria_types(apps, schema_editor):
    CriteriaType = apps.get_model("the_music_tree_genre_kit", "CriteriaType")
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    CriteriaType.objects.get_or_create(pk=1, defaults={"label": "tag"})


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0001_initial"),
        ("the_music_tree_genre_kit", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_criteria_types, noop),
    ]
