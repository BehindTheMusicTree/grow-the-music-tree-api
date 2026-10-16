from django.db import models

from grow.model.artist.Artist import Artist
from grow.model.artist.Fields import Fields as ArtistFields


class ArtistLink(models.Model):
    """A curated external link of an artist, from MusicBrainz artist-URL relationships."""

    class Kind(models.TextChoices):
        OFFICIAL = "official"
        WIKIPEDIA = "wikipedia"
        WIKIDATA = "wikidata"
        SPOTIFY = "spotify"
        YOUTUBE = "youtube"
        BANDCAMP = "bandcamp"
        SOUNDCLOUD = "soundcloud"
        DISCOGS = "discogs"
        SOCIAL = "social"

    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name=ArtistFields.LINKS)
    kind = models.TextField(choices=Kind.choices)
    url = models.TextField()

    class Meta:
        db_table = "grow_artist_link"
        constraints = [models.UniqueConstraint(fields=["artist", "kind", "url"], name="grow_artist_link_unique")]
