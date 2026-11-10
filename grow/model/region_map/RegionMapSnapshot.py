from django.db import models

from grow.model.import_run.ImportRun import ImportRun


class RegionMapSnapshot(models.Model):
    """One pipeline export of the region map. `checksum` is its index's sha256, which is also the index's
    `RegionMapFile`. `hidden_regions_checksum` is the sha256
    of the `RegionMapFile` listing the hidden regions; null means the previous format, where the index lists them."""

    created_on = models.DateTimeField(auto_now_add=True)
    checksum = models.CharField(max_length=64, unique=True)
    hidden_regions_checksum = models.CharField(max_length=64, null=True)
    import_run = models.ForeignKey(ImportRun, null=True, on_delete=models.PROTECT, related_name="region_map_snapshots")

    class Meta:
        db_table = "grow_region_map_snapshot"
        ordering = ["-created_on", "-pk"]
