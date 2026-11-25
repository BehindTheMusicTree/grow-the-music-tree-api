from the_music_tree_genre_kit.filtering.set.criteria_playlist.CriteriaPlaylistFilterSet import CriteriaPlaylistFilterSet

from grow.genre_graph.snapshot import graph_snapshot
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.serializer.model.playlist.children.criteria.output.detailed import CriteriaPlaylistDetailedSerializer
from grow.serializer.model.playlist.children.criteria.output.simple import CriteriaPlaylistSimpleSerializer
from grow.serializer.model.track_playlist_rel.output.in_page import TrackPlaylistRelInPageSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet
from grow.view.viewset.model.playlist.RegionPlaylistTracksMixin import TRACKS_SCHEMA, RegionPlaylistTracksMixin


@TRACKS_SCHEMA
class CriteriaPlaylistViewSet(RegionPlaylistTracksMixin, GrowModelViewSet[CriteriaPlaylist]):
    track_playlist_rel_serializer_class = TrackPlaylistRelInPageSerializer

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .exclude(criteria__semantic_identity__isnull=False, criteria__graph_node__is_active=False)
        )

    def __init__(self, model_class: type[CriteriaPlaylist], **kwargs):
        super().__init__(
            model_class=model_class,
            filterset_class=CriteriaPlaylistFilterSet,
            simple_serializer_class=CriteriaPlaylistSimpleSerializer,
            detailed_serializer_class=CriteriaPlaylistDetailedSerializer,
            **kwargs,
        )

    @graph_snapshot
    def list(self, *args, **kwargs):
        return self._handle_list()

    @graph_snapshot
    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()
