from django.contrib.postgres.search import SearchVectorField
from django.db import models

from grow.model.song_search.SongSearchManager import SongSearchManager


class SongSearch(models.Model):
    """
    Search projection of every song, derived by `grow/song_search/projection.py`: kept in sync by the bulk merges and
    the song ORM writes, rebuilt from scratch by `rebuild_song_search`. Never edited directly.
    """

    # No database FK: the rebuild swaps in a freshly filled table by renaming it, and `drift()` checks consistency.
    track = models.OneToOneField(
        "grow.Song", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="search"
    )
    document = SearchVectorField()
    title_key = models.TextField()
    has_genre = models.BooleanField()
    playable = models.BooleanField()
    rank_score = models.IntegerField()

    objects = SongSearchManager()

    class Meta:
        db_table = "grow_song_search"
        # The GIN index on `document` and the `title_key COLLATE "C"` index are Postgres-only (migration 0098).
        indexes = [models.Index(fields=["-rank_score", "track"], name="grow_song_search_rank_idx")]
