import json
from pathlib import Path

from django.db import migrations

SEED = Path(__file__).with_suffix(".json")
"""The seeded `[list_name, key, values, reason]` entries, frozen so this migration never depends on the current
curation registry or seed CSVs."""


def seed(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    if CurationEntry.objects.exists():
        return
    CurationEntry.objects.bulk_create(
        CurationEntry(user=None, list_name=list_name, key=key, values=values, reason=reason)
        for list_name, key, values, reason in json.loads(SEED.read_text(encoding="utf-8"))
    )


class Migration(migrations.Migration):
    dependencies = [("grow", "0034_curation_entry")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
