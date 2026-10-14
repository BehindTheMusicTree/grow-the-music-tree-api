from django.db import models


class ArtistImportStaging(models.Model):
    """One uploaded artist row, kept as validated JSON. UNLOGGED on Postgres like `SongImportStaging`."""

    run_id = models.BigIntegerField()
    part = models.PositiveIntegerField()
    musicbrainz_artist_id = models.UUIDField()
    data = models.JSONField()

    class Meta:
        db_table = "grow_artist_import_staging"
        indexes = [models.Index(fields=["run_id", "part"], name="grow_artist_staging_run_idx")]
