from django.db import models

from grow.model.artist.Artist import Artist
from grow.model.artist.Fields import Fields as ArtistFields


class ArtistAlias(models.Model):
    """An alternate name of an artist (MusicBrainz aliases and sort names), searched alongside the artist's name."""

    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name=ArtistFields.ALIASES)
    name = models.TextField()

    class Meta:
        db_table = "grow_artist_alias"
        constraints = [models.UniqueConstraint(fields=["artist", "name"], name="grow_artist_alias_unique")]
