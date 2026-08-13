from grow.filtering.set.play.PlayFilterSet import PlayFilterSet
from grow.model.play.Play import Play
from grow.serializer.model.play.input.schema.post import PlayPostSerializer
from grow.serializer.model.play.output.detailed import PlayDetailedSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class PlayViewSet(GrowModelViewSet[Play]):
    def __init__(self, **kwargs):
        super().__init__(
            model_class=Play,
            filterset_class=PlayFilterSet,
            simple_serializer_class=PlayDetailedSerializer,
            detailed_serializer_class=PlayDetailedSerializer,
            create_serializer_class=PlayPostSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def create(self, request, *args, **kwargs):
        return self._handle_post(request)
