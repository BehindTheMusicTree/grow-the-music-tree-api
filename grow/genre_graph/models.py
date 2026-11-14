from django.db import models


class GenreGraphImport(models.Model):
    revision = models.UUIDField(primary_key=True)
    mapping = models.JSONField()
    curation_exported_on = models.DateTimeField()
    created_on = models.DateTimeField(auto_now_add=True)


class GenreGraphAssignmentBackup(models.Model):
    """Original assignments survive deletion of live catalogue rows."""

    imported = models.ForeignKey(GenreGraphImport, on_delete=models.PROTECT)
    song_uuid = models.UUIDField()
    genre_uuid = models.UUIDField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["imported", "song_uuid"], name="graph_backup_song_unique")]
