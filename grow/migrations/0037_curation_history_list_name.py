import json

from django.db import migrations


def add_list_name(apps, schema_editor):
    """Adds `list_name` to curation history snapshots of entries still alive; a deleted entry's list is lost."""
    content_type = apps.get_model("contenttypes", "ContentType").objects.filter(app_label="grow", model="curationentry")
    list_names = dict(apps.get_model("grow", "CurationEntry").objects.values_list("uuid", "list_name"))
    histories = apps.get_model("grow", "HistoryEntry").objects.filter(
        content_type__in=content_type, content_uuid__in=list_names
    )
    changed = []
    for history in histories:
        for field in ("old_value", "new_value"):
            value = getattr(history, field)
            if value is not None and "list_name" not in (row := json.loads(value)):
                setattr(history, field, json.dumps({"list_name": list_names[history.content_uuid], **row}))
        changed.append(history)
    apps.get_model("grow", "HistoryEntry").objects.bulk_update(changed, ["old_value", "new_value"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("contenttypes", "0002_remove_content_type_name"), ("grow", "0036_locked_genres_to_curation_entries")]

    operations = [migrations.RunPython(add_list_name, migrations.RunPython.noop)]
