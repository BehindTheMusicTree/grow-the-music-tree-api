from django.db import transaction
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from the_music_tree_api_kit.private.get_request_owner import get_request_owner
from the_music_tree_api_kit.serializer.SerializerType import SerializerType

from grow.model.criteria.children.genre.Genre import Genre
from grow.serializer.model.criteria.children.genre.input.post import GenrePostSerializer
from grow.serializer.model.criteria.children.genre.input.put import GenrePutSerializer
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin
from grow.view.viewset.model.criteria.CriteriaViewSet import CriteriaViewSet
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin


class GenreViewSet(HistoryActionMixin, CriteriaViewSet):
    def __init__(self, **kwargs):
        super().__init__(
            model_class=Genre,
            create_serializer_class=GenrePostSerializer,
            update_serializer_class=GenrePutSerializer,
            **kwargs,
        )

    @action(detail=False, methods=["post"], url_path="tree/import", permission_classes=[IsPipelineOrAdmin])
    def import_tree(self, request):
        with transaction.atomic():
            response = super().import_tree(request)
            Genre.objects.assert_required_roots_present(get_request_owner(request))

        return response

    @action(detail=True, methods=["post"])
    def exclude(self, request: Request, *args, **kwargs) -> Response:
        instance = Genre.objects.exclude_instance(self.get_object(), **self._get_manager_write_kwargs(request))
        serializer = self._require_serializer(SerializerType.DETAILED)(instance=instance)
        return Response(data=serializer.data)
