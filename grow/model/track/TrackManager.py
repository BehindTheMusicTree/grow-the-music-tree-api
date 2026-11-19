from typing import TYPE_CHECKING, Any, TypeVar

from django.db import transaction
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.track.AbstractTrackManager import AbstractTrackManager

from grow.genre_music.source_gate import lock_catalogue_sources
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry

if TYPE_CHECKING:
    from the_music_tree_genre_kit.track.Track import Track

T = TypeVar("T", bound="Track")


class TrackManager(AbstractTrackManager[T]):
    def _is_playable(self, instance: T) -> bool:
        # Mirrored by PLAYABLE in grow/model/song/playable.py, grow/track/bulk_import/merge.py and migration 0051:
        # keep the four in sync.
        return instance.youtube_video_id is not None and instance.youtube_unplayable_reason is None

    def create(self, actor: Any = None, **kwargs) -> T:
        with transaction.atomic():
            lock_catalogue_sources(using=self.db)
            instance = super().create(actor=actor, **kwargs)
            self._refresh_search(instance)
            self._refresh_artist_songs(instance)
        return instance

    @transaction.atomic
    def update_instance(self, old_instance: T, actor: Any = None, **kwargs) -> T:
        # A trigger cannot refresh the application's already-loaded old genre.
        # Serialize before reloading, so membership updates use committed state.
        lock_catalogue_sources(using=self.db)
        old_instance.refresh_from_db(using=self.db)
        return super().update_instance(old_instance, actor=actor, **kwargs)

    @transaction.atomic
    def delete_instance(self, instance: T, actor: Any = None):
        lock_catalogue_sources(using=self.db)
        instance.refresh_from_db(using=self.db)
        return super().delete_instance(instance, actor=actor)

    def record_semantic_genre_change(self, instance: T, *, old_genre, actor: Any = None) -> None:
        """Side effects of a genre change made through attributions, where no column changed."""
        from grow.genre_graph.service import song_genre

        self._on_track_genre_changed(instance, old_genre=old_genre, actor=actor)
        if self._is_playable(instance):
            old_playlists = super()._genre_playlists(instance, old_genre)
            new_playlists = super()._genre_playlists(instance, song_genre(instance))
            present = set(
                TrackPlaylistRel.objects.filter(user=instance.user, track=instance).values_list(
                    "playlist_id", flat=True
                )
            )
            for playlist_pk in new_playlists.keys() - old_playlists.keys() - present:
                TrackPlaylistRel.objects.create(user=instance.user, playlist=new_playlists[playlist_pk], track=instance)
            self._remove_from_playlists(
                instance,
                {pk: old_playlists[pk] for pk in (old_playlists.keys() - new_playlists.keys()) & present},
                old_genre,
            )
        self._refresh_search(instance)

    def _on_updated(self, old_instance: T, updated_instance: T) -> None:
        self._refresh_search(updated_instance)
        self._refresh_artist_songs(updated_instance)

    @staticmethod
    def _refresh_artist_songs(instance: T) -> None:
        # Deletions need no hook: the rows cascade with their song or artist.
        from grow.model.artist_song.ArtistSong import ArtistSong

        ArtistSong.objects.refresh_songs([instance.pk])

    @staticmethod
    def _refresh_search(instance: T) -> None:
        from grow.model.song_search.SongSearch import SongSearch

        SongSearch.objects.refresh([instance.pk])

    def _on_track_genre_changed(self, instance: T, *, old_genre, actor: Any = None) -> None:
        if actor is not None and self._model_has_manual_edit_field():
            instance.is_manually_edited = True
            instance.save(update_fields=["is_manually_edited"])
        from grow.genre_graph.service import song_genre

        new_genre = song_genre(instance)
        HistoryEntry.objects.record(
            instance,
            action=HistoryAction.GENRE_CHANGED,
            actor=actor,
            old_value=old_genre.name if old_genre else None,
            new_value=new_genre.name if new_genre else None,
        )
