from django.db import transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from the_music_tree_api_kit.private.get_request_owner import get_request_owner
from the_music_tree_api_kit.serializer.SerializerType import SerializerType
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.import_run.ImportRun import ImportRun
from grow.serializer.model.criteria.children.genre.input.exclude import GenreExcludeSerializer
from grow.serializer.model.criteria.children.genre.input.name_conflict_validate import (
    GenreNameConflictValidateSerializer,
)
from grow.serializer.model.criteria.children.genre.input.post import GenrePostSerializer
from grow.serializer.model.criteria.children.genre.input.put import GenrePutSerializer
from grow.serializer.model.criteria.children.genre.input.unaccepted_root_accept import (
    GenreUnacceptedRootAcceptSerializer,
)
from grow.serializer.model.criteria.children.genre.output.name_conflict_group import GenreNameConflictGroupSerializer
from grow.serializer.model.criteria.children.genre.output.simple import GenreSimpleSerializer
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin
from grow.view.viewset.model.criteria.CriteriaViewSet import CriteriaViewSet
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin

TREE_IMPORT_RUN_KINDS = {
    CriteriaTreeName.CANONICAL: ImportRun.Kind.CANONICAL_TREE,
    CriteriaTreeName.REGIONAL: ImportRun.Kind.REGIONAL_TREE,
}


def _node_count(nodes: list[dict]) -> int:
    return sum(1 + _node_count(node.get(Fields.CHILDREN) or []) for node in nodes)


class GenreViewSet(HistoryActionMixin, CriteriaViewSet):
    def __init__(self, **kwargs):
        from grow.filtering.set.criteria.children.genre.GenreFilterSet import GenreFilterSet

        super().__init__(
            model_class=Genre,
            simple_serializer_class=GenreSimpleSerializer,
            filterset_class=GenreFilterSet,
            create_serializer_class=GenrePostSerializer,
            update_serializer_class=GenrePutSerializer,
            **kwargs,
        )

    @action(detail=False, methods=["post"], url_path="tree/import", permission_classes=[IsPipelineOrAdmin])
    def import_tree(self, request):
        with transaction.atomic():
            response = super().import_tree(request)
            Genre.objects.assert_required_roots_present(get_request_owner(request))
            if request.auth.role == "pipeline":
                state = CurationSyncState.load()
                state.applied_export_on = state.exported_on
                state.save(update_fields=["applied_export_on"])
                ImportRun.objects.create(
                    kind=TREE_IMPORT_RUN_KINDS[request.data[Fields.TREE_NAME]],
                    count=_node_count(request.data[Fields.TREE]),
                )

        return response

    @action(detail=True, methods=["post"])
    def exclude(self, request: Request, *args, **kwargs) -> Response:
        genre = self.get_object()
        input_serializer = GenreExcludeSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        instance = Genre.objects.exclude_instance(
            genre, input_serializer.validated_data["category"], **self._get_manager_write_kwargs(request)
        )
        serializer = self._require_serializer(SerializerType.DETAILED)(instance=instance)
        return Response(data=serializer.data)

    @action(detail=False, methods=["get"], url_path="name-conflicts")
    def name_conflicts(self, request: Request) -> Response:
        groups = Genre.objects.get_name_conflict_groups(get_request_owner(request))
        return Response(data=GenreNameConflictGroupSerializer(groups, many=True).data)

    @action(detail=False, methods=["post"], url_path="name-conflicts/validate")
    def validate_name_conflicts(self, request: Request) -> Response:
        serializer = GenreNameConflictValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        Genre.objects.validate_name_conflict_group(
            get_request_owner(request),
            {genre["uuid"]: genre["name"] for genre in serializer.validated_data["genres"]},
            **self._get_manager_write_kwargs(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="unaccepted-roots")
    def unaccepted_roots(self, request: Request) -> Response:
        genres = Genre.objects.get_unaccepted_roots(get_request_owner(request))
        return Response(data=GenreSimpleSerializer(genres, many=True).data)

    @action(detail=False, methods=["post"], url_path="unaccepted-roots/accept")
    def accept_unaccepted_roots(self, request: Request) -> Response:
        serializer = GenreUnacceptedRootAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        Genre.objects.accept_roots(
            get_request_owner(request),
            [genre["uuid"] for genre in serializer.validated_data["genres"]],
            **self._get_manager_write_kwargs(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
