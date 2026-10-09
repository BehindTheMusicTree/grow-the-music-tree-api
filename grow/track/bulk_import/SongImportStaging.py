from django.db import models


class SongImportStaging(models.Model):
    """One uploaded song row. UNLOGGED on Postgres (see migration): a crash only loses rows a retry re-uploads."""

    run_id = models.BigIntegerField()
    part = models.PositiveIntegerField()
    musicbrainz_recording_id = models.UUIDField()
    title = models.TextField()
    artist = models.TextField()
    youtube_video_id = models.TextField(null=True)
    youtube_unplayable_reason = models.TextField(null=True)
    genre_name = models.TextField(null=True)

    class Meta:
        db_table = "grow_song_import_staging"
        indexes = [models.Index(fields=["run_id", "part"], name="grow_song_staging_run_part_idx")]
