from django.db import migrations


def drop_geometry_snapshots(apps, schema_editor):
    """Snapshots in the old format list GeoJSON files and no tileset, and their files are gone: drop them so the index
    answers 404 until the pipeline imports the first tileset-based region map. Not reversible (data is not restored)."""
    apps.get_model("grow", "RegionMapSnapshot").objects.all().delete()
    apps.get_model("grow", "RegionMapFile").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0089_region_overrides_curation_list"),
    ]

    operations = [
        migrations.DeleteModel(name="RegionMapSnapshotFile"),
        migrations.RunPython(drop_geometry_snapshots, migrations.RunPython.noop),
    ]
