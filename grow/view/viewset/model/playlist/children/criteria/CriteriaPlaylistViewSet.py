from the_music_tree_genre_kit.view.viewset.playlist.PlaylistTracksActionMixin import PlaylistTracksActionMixin

from grow.filtering.set.playlist.children.criteria.CriteriaPlaylistFilterSet import CriteriaPlaylistFilterSet
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.serializer.model.playlist.children.criteria.output.detailed import CriteriaPlaylistDetailedSerializer
from grow.serializer.model.playlist.children.criteria.output.simple import CriteriaPlaylistSimpleSerializer
from grow.serializer.model.track_playlist_rel.output.in_page import TrackPlaylistRelInPageSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class CriteriaPlaylistViewSet(PlaylistTracksActionMixin, GrowModelViewSet[CriteriaPlaylist]):
    track_playlist_rel_serializer_class = TrackPlaylistRelInPageSerializer

    def __init__(self, model_class: type[CriteriaPlaylist], **kwargs):
        super().__init__(
            model_class=model_class,
            filterset_class=CriteriaPlaylistFilterSet,
            simple_serializer_class=CriteriaPlaylistSimpleSerializer,
            detailed_serializer_class=CriteriaPlaylistDetailedSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()
