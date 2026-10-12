from django.contrib.contenttypes.models import ContentType
from django.db import models

from grow.model.curation.CurationEntry import CurationEntry
from grow.model.history.HistoryEntry import HistoryEntry


class CurationSyncState(models.Model):
    """Singleton: when the pipeline last exported curation, and which export the canonical tree was last built from."""

    exported_on = models.DateTimeField(null=True)
    applied_export_on = models.DateTimeField(null=True)

    class Meta:
        db_table = "grow_curation_sync_state"

    @classmethod
    def load(cls) -> CurationSyncState:
        return cls.objects.get_or_create(pk=1)[0]

    @property
    def pending_count(self) -> int:
        """Canonical curation entries created, edited or deleted since the applied export."""
        history = HistoryEntry.objects.filter(user=None, content_type=ContentType.objects.get_for_model(CurationEntry))
        if self.applied_export_on is not None:
            history = history.filter(created_on__gt=self.applied_export_on)
        return history.values("content_uuid").distinct().count()
