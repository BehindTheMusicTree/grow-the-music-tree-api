from __future__ import annotations

from django.db import models


class ArtistSongState(models.Model):
    """Singleton: the artist song list is served only once `rebuild_artist_song` has filled the projection."""

    ready = models.BooleanField(default=False)
    rebuilt_on = models.DateTimeField(null=True)

    class Meta:
        db_table = "grow_artist_song_state"

    @classmethod
    def load(cls) -> ArtistSongState:
        return cls.objects.get_or_create(pk=1)[0]
