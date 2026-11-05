from django.apps import AppConfig
from django.db.models.signals import post_delete


class GrowConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "grow"

    def ready(self) -> None:
        from the_music_tree_genre_kit.track.Track import Track

        from grow.search.cache import on_track_deleted as invalidate_song_search_cache
        from grow.track.direct_songs_count import on_track_deleted

        # Songs also disappear through album and artist cascades, which no manager hook sees.
        post_delete.connect(on_track_deleted, sender=Track, dispatch_uid="grow_direct_songs_count_track_deleted")
        post_delete.connect(
            invalidate_song_search_cache, sender=Track, dispatch_uid="grow_song_search_cache_track_deleted"
        )
