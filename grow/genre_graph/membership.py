"""Read the direct catalogue assignment from the database's current source state."""

from django.db import models


class SongMembership(models.Model):
    track = models.OneToOneField(
        "the_music_tree_genre_kit.Track",
        primary_key=True,
        on_delete=models.DO_NOTHING,
        related_name="song_membership",
    )
    genre = models.ForeignKey("grow.Genre", null=True, on_delete=models.DO_NOTHING, related_name="+")

    class Meta:
        managed = False
        db_table = "grow_song_membership"
