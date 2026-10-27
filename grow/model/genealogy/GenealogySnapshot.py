from django.db import models

from grow.model.import_run.ImportRun import ImportRun


class GenealogySnapshot(models.Model):
    """One pipeline export of the music-tradition genealogy, stored whole: the frontend renders it and never queries inside."""

    created_at = models.DateTimeField(auto_now_add=True)
    document = models.JSONField()
    checksum = models.CharField(max_length=64)
    import_run = models.ForeignKey(ImportRun, null=True, on_delete=models.PROTECT, related_name="genealogy_snapshots")

    class Meta:
        db_table = "grow_genealogy_snapshot"
        ordering = ["-created_at", "-pk"]
