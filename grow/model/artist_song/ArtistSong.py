from django.db import models

from grow.model.artist_song.ArtistSongManager import ArtistSongManager


class ArtistSong(models.Model):
    """
    One row per (artist, song) credit with the song's sort keys, derived by `grow/artist_song/projection.py`: kept in
    sync by the bulk merges and the song ORM writes, rebuilt from scratch by `rebuild_artist_song`. Never edited
    directly.
    """

    # No database FKs: the rebuild swaps in a freshly filled table by renaming it, and `drift()` checks consistency.
    # A composite key: no surrogate sequence for the rebuild's table swap to orphan.
    pk = models.CompositePrimaryKey("artist", "song")
    artist = models.ForeignKey("grow.Artist", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    song = models.ForeignKey("grow.Song", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    title = models.TextField()
    album_year = models.SmallIntegerField(null=True)

    objects = ArtistSongManager()

    class Meta:
        db_table = "grow_artist_song"
        # The two keyset indexes (title ascending, year descending with NULLS LAST) are Postgres-only (migration 0146).
