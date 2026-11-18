from the_music_tree_genre_kit.filtering.set.playlist.PlaylistFilterSet import PlaylistFilterSet
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.genre_graph.snapshot import graph_snapshot
from grow.serializer.model.playlist.base.output.detailed import PlaylistDetailedSerializer
from grow.serializer.model.playlist.base.output.simple import PlaylistSimpleSerializer
from grow.serializer.model.track_playlist_rel.output.in_page import TrackPlaylistRelInPageSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet
from grow.view.viewset.model.playlist.RegionPlaylistTracksMixin import RegionPlaylistTracksMixin


class PlaylistViewSet(RegionPlaylistTracksMixin, GrowModelViewSet[Playlist]):
    track_playlist_rel_serializer_class = TrackPlaylistRelInPageSerializer

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .exclude(
                criteria_playlist__criteria__semantic_identity__isnull=False,
                criteria_playlist__criteria__graph_node__is_active=False,
            )
        )

    def __init__(self, **kwargs):
        super().__init__(
            model_class=Playlist,
            filterset_class=PlaylistFilterSet,
            simple_serializer_class=PlaylistSimpleSerializer,
            detailed_serializer_class=PlaylistDetailedSerializer,
            **kwargs,
        )

    @graph_snapshot
    def list(self, *args, **kwargs):
        return self._handle_list()

    @graph_snapshot
    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()
