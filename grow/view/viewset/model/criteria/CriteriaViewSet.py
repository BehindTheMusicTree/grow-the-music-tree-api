from rest_framework.response import Response
from the_music_tree_genre_kit.view.viewset.AbstractCriteriaViewSet import AbstractCriteriaViewSet

from grow.model.criteria.Criteria import Criteria
from grow.serializer.model.criteria.input.post import CriteriaPostSerializer
from grow.serializer.model.criteria.input.put import CriteriaPutSerializer
from grow.serializer.model.criteria.output.detailed import CriteriaDetailedSerializer
from grow.serializer.model.criteria.output.simple import CriteriaSimpleSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class CriteriaViewSet(AbstractCriteriaViewSet[Criteria], GrowModelViewSet[Criteria]):
    def __init__(self, model_class: type[Criteria], **kwargs):
        # Filtersets must be imported after Django is loaded
        from grow.filtering.set.criteria.CriteriaFilterSet import CriteriaFilterSet

        super().__init__(
            model_class=model_class,
            filterset_class=CriteriaFilterSet,
            simple_serializer_class=CriteriaSimpleSerializer,
            detailed_serializer_class=CriteriaDetailedSerializer,
            create_serializer_class=CriteriaPostSerializer,
            update_serializer_class=CriteriaPutSerializer,
            **kwargs,
        )

    def create(self, request, *args, **kwargs):
        return self._handle_post(request)

    def destroy(self, request, *args, **kwargs):
        """
        Delete a criteria.

        When deleting a criteria:
        - If it has children and a parent, children are reassigned to the parent
        - If it has children but no parent, children become root criteria
        - If it's a root criteria, tracks are moved to the criterialess playlist
        - The criteria playlist is deleted along with the criteria
        """
        return self._handle_destroy()

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs) -> Response:
        return self._handle_retrieve()

    def update(self, request, *args, **kwargs):
        return self._handle_update(request)
