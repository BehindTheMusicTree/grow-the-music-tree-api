from django.db import models


class RegionMapFile(models.Model):
    """One region map document (the index or a GeoJSON file), stored gzip-compressed once per content hash and shared by
    every snapshot listing it, so it is served as-is at an immutable URL."""

    sha256 = models.CharField(max_length=64, primary_key=True)
    body = models.BinaryField()
    size = models.PositiveIntegerField()

    class Meta:
        db_table = "grow_region_map_file"
