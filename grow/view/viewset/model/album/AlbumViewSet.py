from grow.filtering.set.album.AlbumFilterSet import AlbumFilterSet
from grow.model.album.Album import Album
from grow.serializer.model.album.detailed import AlbumDetailedSerializer
from grow.serializer.model.album.simple import AlbumSimpleSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class AlbumViewSet(GrowModelViewSet[Album]):
    def __init__(self, **kwargs):
        super().__init__(
            model_class=Album,
            filterset_class=AlbumFilterSet,
            simple_serializer_class=AlbumSimpleSerializer,
            detailed_serializer_class=AlbumDetailedSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def destroy(self, *args, **kwargs):
        return self._handle_destroy()
