from django.contrib.contenttypes.models import ContentType
from django.db import models

from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
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
        """Canonical curation entries and edges created, edited or deleted since the applied export."""
        content_types = ContentType.objects.get_for_models(CurationEntry, GenreEdgeRule).values()
        history = HistoryEntry.objects.filter(user=None, content_type__in=content_types)
        if self.applied_export_on is not None:
            history = history.filter(created_on__gt=self.applied_export_on)
        return history.values("content_uuid").distinct().count()
