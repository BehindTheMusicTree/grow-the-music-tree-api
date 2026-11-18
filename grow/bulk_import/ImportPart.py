from django.db import models

from grow.bulk_import.BulkImportRun import BulkImportRun


class ImportPart(models.Model):
    """Logged upload receipts survive a reset of the unlogged staging tables."""

    run = models.ForeignKey(BulkImportRun, on_delete=models.CASCADE, related_name="parts")
    stream = models.TextField()
    part = models.PositiveIntegerField()
    row_count = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        db_table = "grow_import_part"
        constraints = [models.UniqueConstraint(fields=["run", "stream", "part"], name="grow_import_part_unique")]
