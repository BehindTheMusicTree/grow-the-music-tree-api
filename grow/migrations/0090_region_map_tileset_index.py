from django.db import migrations


def drop_geometry_blobs(apps, schema_editor):
    """The geometry now lives in an immutable tileset on object storage: keep only the latest snapshot and its index."""
    Snapshot = apps.get_model("grow", "RegionMapSnapshot")
    File = apps.get_model("grow", "RegionMapFile")
    latest = Snapshot.objects.first()
    if latest is None:
        File.objects.all().delete()
        return
    Snapshot.objects.exclude(pk=latest.pk).delete()
    File.objects.exclude(sha256=latest.checksum).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0089_region_overrides_curation_list"),
    ]

    operations = [
        migrations.DeleteModel(name="RegionMapSnapshotFile"),
        migrations.RunPython(drop_geometry_blobs, migrations.RunPython.noop),
    ]
