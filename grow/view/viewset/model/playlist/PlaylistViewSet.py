from the_music_tree_genre_kit.playlist.Playlist import Playlist
from the_music_tree_genre_kit.view.viewset.playlist.PlaylistTracksActionMixin import PlaylistTracksActionMixin

from grow.filtering.set.playlist.PlaylistFilterSet import PlaylistFilterSet
from grow.serializer.model.playlist.base.output.detailed import PlaylistDetailedSerializer
from grow.serializer.model.playlist.base.output.simple import PlaylistSimpleSerializer
from grow.serializer.model.track_playlist_rel.output.in_page import TrackPlaylistRelInPageSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class PlaylistViewSet(PlaylistTracksActionMixin, GrowModelViewSet[Playlist]):
    track_playlist_rel_serializer_class = TrackPlaylistRelInPageSerializer

    def __init__(self, **kwargs):
        super().__init__(
            model_class=Playlist,
            filterset_class=PlaylistFilterSet,
            simple_serializer_class=PlaylistSimpleSerializer,
            detailed_serializer_class=PlaylistDetailedSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()
