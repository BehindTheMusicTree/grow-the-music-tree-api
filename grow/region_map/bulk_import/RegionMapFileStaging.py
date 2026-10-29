from django.db import models


class RegionMapFileStaging(models.Model):
    """One uploaded region map file, already canonical and gzip-compressed. UNLOGGED on Postgres like
    `SongImportStaging`."""

    run_id = models.BigIntegerField()
    part = models.PositiveIntegerField()
    path = models.TextField()
    sha256 = models.CharField(max_length=64)
    body = models.BinaryField()

    class Meta:
        db_table = "grow_region_map_file_staging"
        indexes = [models.Index(fields=["run_id", "part"], name="grow_region_staging_run_idx")]
