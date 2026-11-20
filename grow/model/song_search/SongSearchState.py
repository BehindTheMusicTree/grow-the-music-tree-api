from django.db import models


class SongSearchState(models.Model):
    """Singleton: the song search projection serves queries only once `rebuild_song_search` has filled it."""

    ready = models.BooleanField(default=False)
    rebuilt_on = models.DateTimeField(null=True)
    # Hash of the definition that built the table (see `grow.projection.fingerprint`); only a full rebuild or a clean
    # drift check sets it, never an incremental merge. Null: unknown.
    fingerprint = models.CharField(max_length=64, null=True)

    class Meta:
        db_table = "grow_song_search_state"

    @classmethod
    def load(cls) -> SongSearchState:
        return cls.objects.get_or_create(pk=1)[0]
