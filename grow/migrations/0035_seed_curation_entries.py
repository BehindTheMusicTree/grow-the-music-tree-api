from django.db import migrations

from grow.curation.rows import SEED_DIR, import_csv_dir


def seed(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    if CurationEntry.objects.exists():
        return
    import_csv_dir(CurationEntry, SEED_DIR)


class Migration(migrations.Migration):
    dependencies = [("grow", "0034_curation_entry")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
