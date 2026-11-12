from django.conf import settings
from django.db import models


class GenreEssentialSong(models.Model):
    """Through row of `Genre.essential_songs`; `position` keeps the curated order (1-based, gaps allowed)."""

    genre = models.ForeignKey("grow.Genre", on_delete=models.CASCADE)
    song = models.ForeignKey(settings.TRACK_MODEL, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "grow_genre_essential_songs"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["genre", "song"], name="grow_genre_essential_song_unique"),
            models.UniqueConstraint(fields=["genre", "position"], name="grow_genre_essential_position_unique"),
        ]
