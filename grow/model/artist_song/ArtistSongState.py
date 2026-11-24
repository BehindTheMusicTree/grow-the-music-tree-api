from __future__ import annotations

from django.db import models


class ArtistSongState(models.Model):
    """Singleton: the artist song list is served only once `rebuild_artist_song` has filled the projection."""

    ready = models.BooleanField(default=False)
    rebuilt_on = models.DateTimeField(null=True)
    # Hash of the definition that built the table (see `grow.projection.fingerprint`); only a full rebuild or a clean
    # drift check sets it, never an incremental merge. Null: unknown.
    fingerprint = models.CharField(max_length=64, null=True)

    class Meta:
        db_table = "grow_artist_song_state"

    @classmethod
    def load(cls) -> ArtistSongState:
        return cls.objects.get_or_create(pk=1)[0]
