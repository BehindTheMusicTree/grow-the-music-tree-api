from django.db import models


class SongAssignmentStaging(models.Model):
    """Complete semantic assignments for one recording in an uploaded part."""

    run_id = models.BigIntegerField()
    part = models.PositiveIntegerField()
    musicbrainz_recording_id = models.UUIDField()
    assignments = models.JSONField()

    class Meta:
        db_table = "grow_song_assignment_staging"
        indexes = [
            models.Index(fields=["run_id", "part"], name="grow_assign_stage_run_part_idx"),
            models.Index(fields=["run_id", "musicbrainz_recording_id"], name="grow_assign_stage_run_mbid_idx"),
        ]
