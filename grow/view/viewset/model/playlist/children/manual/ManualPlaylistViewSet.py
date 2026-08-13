from grow.filtering.set.playlist.children.manual.ManualPlaylistFilterSet import ManualPlaylistFilterSet
from grow.model.playlist.children.manual.ManualPlaylist import ManualPlaylist
from grow.serializer.model.playlist.children.manual.input.post import ManualPlaylistPostSerializer
from grow.serializer.model.playlist.children.manual.input.put import ManualPlaylistPutSerializer
from grow.serializer.model.playlist.children.manual.output.detailed import ManualPlaylistDetailedSerializer
from grow.serializer.model.playlist.children.manual.output.simple import ManualPlaylistSimpleSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class ManualPlaylistViewSet(GrowModelViewSet[ManualPlaylist]):
    def __init__(self, **kwargs):
        super().__init__(
            model_class=ManualPlaylist,
            filterset_class=ManualPlaylistFilterSet,
            simple_serializer_class=ManualPlaylistSimpleSerializer,
            detailed_serializer_class=ManualPlaylistDetailedSerializer,
            create_serializer_class=ManualPlaylistPostSerializer,
            update_serializer_class=ManualPlaylistPutSerializer,
            **kwargs,
        )

    def create(self, request, *args, **kwargs):
        return self._handle_post(request)

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def update(self, request, *args, **kwargs):
        return self._handle_update(request)
