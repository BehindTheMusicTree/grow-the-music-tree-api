from grow.filtering.set.artist.ArtistFilterSet import ArtistFilterSet
from grow.model.artist.Artist import Artist
from grow.serializer.model.artist.detailed import ArtistDetailedSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class ArtistViewSet(GrowModelViewSet[Artist]):
    def __init__(self, **kwargs):
        super().__init__(
            model_class=Artist,
            filterset_class=ArtistFilterSet,
            simple_serializer_class=ArtistDetailedSerializer,
            detailed_serializer_class=ArtistDetailedSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def destroy(self, *args, **kwargs):
        return self._handle_destroy()
