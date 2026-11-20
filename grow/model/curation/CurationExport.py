from datetime import timedelta
from typing import Any

from django.db import models

PURGE_AFTER = timedelta(days=30)


class CurationExport(models.Model):
    """A `GET curation/export/` served to the pipeline, kept whole so a tree or graph built from it can be checked
    against exactly what the pipeline read, however many edits came since.

    `snapshot` is the full export response; null only on the row migrated from the former singleton, whose content
    was never recorded."""

    exported_on = models.DateTimeField(unique=True)
    snapshot = models.JSONField(null=True)

    class Meta:
        db_table = "grow_curation_export"

    @classmethod
    def record(cls, exported_on: Any, snapshot: dict[str, Any], applied_export_on: Any) -> CurationExport:
        """Stores an export and purges those over 30 days older than the applied one (a replay of those is rejected)."""
        export = cls.objects.create(exported_on=exported_on, snapshot=snapshot)
        if applied_export_on is not None:
            cls.objects.filter(exported_on__lt=applied_export_on - PURGE_AFTER).delete()
        return export

    @property
    def canonical_roots(self) -> set[str]:
        """The accepted roots the export carried."""
        if self.snapshot is None:
            raise ValueError("This export predates snapshots: its canonical roots were not recorded")
        return {row["item_id"] for row in self.snapshot["canonical_roots"]}
