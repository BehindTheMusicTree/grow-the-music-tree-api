from datetime import datetime

from django.db import transaction
from django.http import QueryDict
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from the_music_tree_api_kit.private.get_request_owner import get_request_owner
from the_music_tree_api_kit.serializer.SerializerType import SerializerType
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.import_run.ImportRun import ImportRun
from grow.model.song.SongCurationManager import SongCurationManager
from grow.serializer.model.criteria.children.genre.input.alias_of import GenreAliasOfSerializer
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
from grow.serializer.model.song.output.without_playlists import SongWithoutPlaylistsSerializer
from grow.view.permission.IsAdmin import IsAdmin
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin
from grow.view.viewset.model.criteria.CriteriaViewSet import CriteriaViewSet
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin

CURATION_EXPORTED_ON = "curation_exported_on"

TREE_IMPORT_RUN_KINDS = {
    CriteriaTreeName.CANONICAL: ImportRun.Kind.CANONICAL_TREE,
    CriteriaTreeName.REGIONAL: ImportRun.Kind.REGIONAL_TREE,
}


def _curation_exported_on(request: Request, state: CurationSyncState) -> datetime:
    """The curation export the imported tree was built from, popped so the tree serializer sees only its own fields.

    A replayed older Gold carries an older export, so edits made since stay pending.
    """
    is_json_object = isinstance(request.data, dict) and not isinstance(request.data, QueryDict)
    value = request.data.pop(CURATION_EXPORTED_ON, None) if is_json_object else None
    if value is None:
        raise ValidationError({CURATION_EXPORTED_ON: "Required: the curation export this tree was built from"})
    try:
        exported_on = serializers.DateTimeField().run_validation(value)
    except ValidationError as e:
        raise ValidationError({CURATION_EXPORTED_ON: e.detail}) from e
    if state.exported_on is None or exported_on > state.exported_on:
        raise ValidationError({CURATION_EXPORTED_ON: "Later than the last curation export"})
    return exported_on


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
        is_pipeline = request.auth.role == "pipeline"
        with transaction.atomic():
            if is_pipeline:
                state = CurationSyncState.load()
                state.applied_export_on = _curation_exported_on(request, state)
            response = super().import_tree(request)
            Genre.objects.assert_required_roots_present(get_request_owner(request))
            if is_pipeline:
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

    def _genre_by_uuid(self, uuid) -> Genre:
        return get_object_or_404(self.get_queryset(), uuid=uuid)

    def _detailed(self, genre: Genre) -> Response:
        return Response(data=self._require_serializer(SerializerType.DETAILED)(instance=genre).data)

    @action(detail=True, methods=["get"], url_path="link-suggestions", permission_classes=[IsAdmin])
    def link_suggestions(self, request: Request, *args, **kwargs) -> Response:
        songs = SongCurationManager.link_suggestions(self.get_object())
        data = SongWithoutPlaylistsSerializer(songs, many=True, context=self.get_serializer_context()).data
        return Response(
            [{**item, "shared_artists": song.shared_artists} for item, song in zip(data, songs, strict=True)]
        )

    @action(
        detail=True,
        methods=["post", "delete"],
        url_path=r"secondary-parents/(?P<parent_uuid>[0-9a-f-]+)",
        permission_classes=[IsAdmin],
    )
    def secondary_parent(self, request: Request, parent_uuid: str, *args, **kwargs) -> Response:
        genre = Genre.objects.set_secondary_parent(
            self.get_object(),
            self._genre_by_uuid(parent_uuid),
            add=request.method == "POST",
            **self._get_manager_write_kwargs(request),
        )
        return self._detailed(genre)

    @action(detail=True, methods=["post"], url_path="alias-of", permission_classes=[IsAdmin])
    def alias_of(self, request: Request, *args, **kwargs) -> Response:
        serializer = GenreAliasOfSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = Genre.objects.alias_instance(
            self.get_object(),
            self._genre_by_uuid(serializer.validated_data["target"]),
            **self._get_manager_write_kwargs(request),
        )
        return self._detailed(target)

    @action(detail=True, methods=["get"], url_path="alias-of/preview", permission_classes=[IsAdmin])
    def alias_of_preview(self, request: Request, *args, **kwargs) -> Response:
        serializer = GenreAliasOfSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        counts = Genre.objects.alias_counts(self.get_object(), self._genre_by_uuid(serializer.validated_data["target"]))
        return Response(counts)
