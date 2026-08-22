from typing import TYPE_CHECKING, TypeVar

from the_music_tree_genre_kit.track.AbstractTrackManager import AbstractTrackManager

if TYPE_CHECKING:
    from the_music_tree_genre_kit.track.Track import Track

T = TypeVar("T", bound="Track")


class TrackManager(AbstractTrackManager[T]):
    pass
