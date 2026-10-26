from django.db import migrations

ADDITION_LISTS = ("canonical_parent_additions", "regional_overview_additions")
DERIVED_LABELS = ("item_label", "parent_label", "recording_label")


def drop_derived_labels(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    for entry in CurationEntry.objects.all().iterator():
        values = dict(entry.values)
        if entry.list_name in ADDITION_LISTS and "item_label" in values:
            values["label"] = values.pop("item_label")
        for column in DERIVED_LABELS:
            values.pop(column, None)
        if values != entry.values:
            entry.values = values
            entry.save(update_fields=["values"])


class Migration(migrations.Migration):

    dependencies = [
        ("grow", "0067_wikidata_item"),
    ]

    operations = [
        migrations.RunPython(drop_derived_labels, migrations.RunPython.noop),
    ]
