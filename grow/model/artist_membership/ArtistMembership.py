from django.db import models

from grow.model.artist.Artist import Artist
from grow.model.artist.Fields import Fields as ArtistFields


class ArtistMembership(models.Model):
    """One period of `member` in `group` (MusicBrainz "member of band"); a member can have several periods."""

    group = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name=ArtistFields.MEMBERS)
    member = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name=ArtistFields.MEMBER_OF)
    begin_year = models.SmallIntegerField(null=True, blank=True)
    end_year = models.SmallIntegerField(null=True, blank=True)
    ended = models.BooleanField(default=False)
    # A JSON list rather than an ArrayField so the SQLite test settings can create the table.
    roles = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "grow_artist_membership"
