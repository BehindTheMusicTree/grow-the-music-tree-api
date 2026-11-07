from typing import Any
from uuid import UUID

from django.db.models import Count, F
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks
from the_music_tree_genre_kit.track.Track import Track


def adjust_direct_songs_count(genre_id: UUID | None, delta: int) -> None:
    """Moves a canonical genre playlist's (Genreless when `genre_id` is None) direct songs count by `delta`."""
    from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist

    GenrePlaylist.objects.filter(user__isnull=True, criteria_id=genre_id).update(
        direct_songs_count=F("direct_songs_count") + delta
    )


def recount_direct_songs_count(song_model: Any, playlist_model: Any) -> None:
    """
    Sets every canonical genre playlist's direct songs count from the songs. Takes the models so a migration can pass
    its historical ones. The delta maintenance elsewhere never recounts: this is the backfill and the tests' oracle.
    """
    counts = dict(song_model.objects.filter(user__isnull=True).order_by().values_list("genre").annotate(n=Count("pk")))
    playlists = list(playlist_model.objects.filter(user__isnull=True, type_id=CriteriaTypePks.GENRE))
    for playlist in playlists:
        playlist.direct_songs_count = counts.get(playlist.criteria_id, 0)
    playlist_model.objects.bulk_update(playlists, ["direct_songs_count"], batch_size=500)


def recount_direct_songs_count_holding_writers(song_model: Any, playlist_model: Any, connection: Any) -> None:
    """The recount, with writers to the playlists held off (on Postgres) until the caller's transaction ends: an import
    merge's delta committed mid-count would otherwise be overwritten by the older count. Readers are not blocked."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("LOCK TABLE grow_criteria_playlist IN SHARE ROW EXCLUSIVE MODE")
    recount_direct_songs_count(song_model, playlist_model)


def on_track_deleted(sender: type[Track], instance: Track, **kwargs: Any) -> None:
    if instance.user_id is None:
        adjust_direct_songs_count(instance.genre_id, -1)
