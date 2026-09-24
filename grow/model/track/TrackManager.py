from typing import TYPE_CHECKING, Any, TypeVar

from the_music_tree_genre_kit.track.AbstractTrackManager import AbstractTrackManager

from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry

if TYPE_CHECKING:
    from the_music_tree_genre_kit.track.Track import Track

T = TypeVar("T", bound="Track")


class TrackManager(AbstractTrackManager[T]):
    def _on_track_genre_changed(self, instance: T, *, old_genre, actor: Any = None) -> None:
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
