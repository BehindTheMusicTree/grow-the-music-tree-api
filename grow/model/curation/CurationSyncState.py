from django.db import models


class CurationSyncState(models.Model):
    """Singleton: when the pipeline last exported curation, and which export the canonical tree was last built from."""

    exported_on = models.DateTimeField(null=True)
    applied_export_on = models.DateTimeField(null=True)

    class Meta:
        db_table = "grow_curation_sync_state"

    @classmethod
    def load(cls) -> CurationSyncState:
        return cls.objects.get_or_create(pk=1)[0]
