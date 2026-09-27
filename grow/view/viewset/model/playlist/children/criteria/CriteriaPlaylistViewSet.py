from grow.filtering.set.playlist.children.criteria.CriteriaPlaylistFilterSet import CriteriaPlaylistFilterSet
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.serializer.model.playlist.children.criteria.output.detailed import CriteriaPlaylistDetailedSerializer
from grow.serializer.model.playlist.children.criteria.output.simple import CriteriaPlaylistSimpleSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class CriteriaPlaylistViewSet(GrowModelViewSet[CriteriaPlaylist]):
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
