from django.db import migrations

RENAMED_LISTS = {
    "canonical_roots": "global_roots",
    "canonical_parent_additions": "global_parent_additions",
    "canonical_genre_scene": "global_genre_scene",
    "canonical_genre_pop_side": "global_genre_pop_side",
    "forced_canonical_genres": "forced_global_genres",
}


def _rename(apps, names):
    for model_name in ("CurationEntry", "CurationReviewItem"):
        model = apps.get_model("grow", model_name)
        for old, new in names.items():
            model.objects.filter(list_name=old).update(list_name=new)


def forward(apps, schema_editor):
    _rename(apps, RENAMED_LISTS)
    apps.get_model("grow", "CurationReviewItem").objects.filter(reason="exclusive_parent_regional").delete()


def backward(apps, schema_editor):
    _rename(apps, {new: old for old, new in RENAMED_LISTS.items()})


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0169_genre_edge_relations"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
