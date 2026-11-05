from django.db import models


class SongSearchState(models.Model):
    """Singleton: the song search projection serves queries only once `rebuild_song_search` has filled it."""

    ready = models.BooleanField(default=False)
    rebuilt_on = models.DateTimeField(null=True)

    class Meta:
        db_table = "grow_song_search_state"

    @classmethod
    def load(cls) -> SongSearchState:
        return cls.objects.get_or_create(pk=1)[0]
