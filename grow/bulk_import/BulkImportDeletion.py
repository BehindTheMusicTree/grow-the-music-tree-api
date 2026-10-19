from django.db import models


class BulkImportDeletion(models.Model):
    """One MBID a delta run deletes; `part` is always 0 so `copy_part` can replace the whole list on a re-upload."""

    run_id = models.BigIntegerField()
    part = models.PositiveIntegerField()
    musicbrainz_id = models.UUIDField()

    class Meta:
        db_table = "grow_bulk_import_deletion"
        indexes = [models.Index(fields=["run_id"], name="grow_bulk_deletion_run_idx")]
