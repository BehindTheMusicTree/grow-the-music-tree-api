from typing import Any

from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination

from grow.model.import_run.ImportRun import ImportRun
from grow.view.curation import CurationView
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin


def _serialize(run: ImportRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {"kind": run.kind, "imported_on": run.imported_on, "count": run.count, "skipped_count": run.skipped_count}


def _newest_first(queryset):
    return queryset.order_by("-imported_on", "-pk")


class UnresolvedGenreTagsReportSerializer(serializers.Serializer):
    unresolved_genre_tag_count = serializers.IntegerField(min_value=0)


class ImportRunUnresolvedGenreTagsView(CurationView):
    """The pipeline's count of song genre tags its Gold stage couldn't match to a genre."""

    permission_classes = [IsPipelineOrAdmin]

    def post(self, request: Request) -> Response:
        serializer = UnresolvedGenreTagsReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = ImportRun.objects.create(
            kind=ImportRun.Kind.UNRESOLVED_GENRE_TAGS, count=serializer.validated_data["unresolved_genre_tag_count"]
        )
        return Response(_serialize(run), status=status.HTTP_201_CREATED)


class ImportRunLatestView(CurationView):
    def get(self, request: Request) -> Response:
        return Response(
            {
                kind.value: _serialize(_newest_first(ImportRun.objects.filter(kind=kind)).first())
                for kind in ImportRun.Kind
            }
        )


class ImportRunListView(CurationView):
    def get(self, request: Request) -> Response:
        queryset = ImportRun.objects.all()
        kind = request.query_params.get("kind")
        if kind is not None:
            if kind not in ImportRun.Kind.values:
                raise ValidationError({"kind": f"Must be one of {', '.join(ImportRun.Kind.values)}"})
            queryset = queryset.filter(kind=kind)
        paginator = AppPagination()
        page = paginator.paginate_queryset(_newest_first(queryset), request, view=self)
        return paginator.get_paginated_response([_serialize(run) for run in page or []])
