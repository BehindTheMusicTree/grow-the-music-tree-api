from django.db import migrations

OLD = "overview_status_overrides"
NEW = "regional_overview_types"
LEGACY_SOURCE = "curation-legacy"
LEGACY_REASON = "Recorded before provenance was required"


def forwards(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    for entry in CurationEntry.objects.filter(list_name=OLD):
        entry.list_name = NEW
        entry.values = {
            "overview_type": entry.values["status"],
            "decision_id": f"legacy-overview-status:{entry.key}",
            "decision_source": LEGACY_SOURCE,
        }
        entry.reason = entry.reason or LEGACY_REASON
        entry.save(update_fields=["list_name", "values", "reason"])
    apps.get_model("grow", "CurationReviewItem").objects.filter(list_name=OLD).update(list_name=NEW)


def backwards(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    for entry in CurationEntry.objects.filter(list_name=NEW):
        entry.list_name = OLD
        entry.values = {"status": entry.values["overview_type"]}
        if entry.reason == LEGACY_REASON:
            entry.reason = ""
        entry.save(update_fields=["list_name", "values", "reason"])
    apps.get_model("grow", "CurationReviewItem").objects.filter(list_name=NEW).update(list_name=OLD)


class Migration(migrations.Migration):
    """History snapshots keep the old list name and shape, as in 0065 and 0102."""

    dependencies = [
        ("grow", "0147_regional_graph_decision_lists"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
