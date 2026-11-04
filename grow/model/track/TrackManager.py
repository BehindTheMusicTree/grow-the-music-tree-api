from typing import TYPE_CHECKING, Any, TypeVar

from django.db import transaction
from the_music_tree_genre_kit.track.AbstractTrackManager import AbstractTrackManager

from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from grow.track.direct_songs_count import adjust_direct_songs_count

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
            instance = super().create(actor=actor, **kwargs)
            if instance.user_id is None:
                adjust_direct_songs_count(instance.genre_id, 1)
        return instance

    def _on_track_genre_changed(self, instance: T, *, old_genre, actor: Any = None) -> None:
        if instance.user_id is None:
            adjust_direct_songs_count(old_genre.pk if old_genre else None, -1)
            adjust_direct_songs_count(instance.genre_id, 1)
        if actor is not None and self._model_has_manual_edit_field():
            instance.is_manually_edited = True
            instance.save(update_fields=["is_manually_edited"])
        HistoryEntry.objects.record(
            instance,
            action=HistoryAction.GENRE_CHANGED,
            actor=actor,
            old_value=old_genre.name if old_genre else None,
            new_value=instance.genre.name if instance.genre else None,
        )
