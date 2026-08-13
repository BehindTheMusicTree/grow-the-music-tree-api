from grow.filtering.set.playlist.PlaylistFilterSet import PlaylistFilterSet
from grow.model.playlist.Playlist import Playlist
from grow.serializer.model.playlist.base.output.detailed import PlaylistDetailedSerializer
from grow.serializer.model.playlist.base.output.simple import PlaylistSimpleSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class PlaylistViewSet(GrowModelViewSet[Playlist]):
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
