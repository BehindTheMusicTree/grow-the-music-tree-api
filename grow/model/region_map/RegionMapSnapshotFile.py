from django.db import models

from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot


class RegionMapSnapshotFile(models.Model):
    """A file of a snapshot, at its path in the export (`index.json` included)."""

    snapshot = models.ForeignKey(RegionMapSnapshot, on_delete=models.CASCADE, related_name="files")
    path = models.TextField()
    file = models.ForeignKey(RegionMapFile, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "grow_region_map_snapshot_file"
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "path"], name="grow_region_map_snapshot_path_unique")
        ]
