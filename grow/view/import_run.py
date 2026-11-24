from typing import Any

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination

from grow.curation.genre_aliases import apply_alias_report
from grow.curation.lists import GRAPH_ITEM_ID_PATTERN
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.import_run.ImportRun import ImportRun
from grow.view.curation import CurationView, _StrictSerializer
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin


def _serialize(run: ImportRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {"kind": run.kind, "imported_on": run.imported_on, "count": run.count, "skipped_count": run.skipped_count}


def _newest_first(queryset):
    return queryset.order_by("-imported_on", "-pk")


class AliasTargetSerializer(_StrictSerializer):
    id = serializers.RegexField(rf"^(?:{GRAPH_ITEM_ID_PATTERN})$")
    label = serializers.CharField(trim_whitespace=False)
    tree = serializers.ChoiceField(choices=("canonical", "regional", "local"))


class AliasExposureSerializer(_StrictSerializer):
    recording = serializers.IntegerField(min_value=0)
    release_group = serializers.IntegerField(min_value=0)
    artist = serializers.IntegerField(min_value=0)
    any = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        counts = [attrs[column] for column in ("recording", "release_group", "artist")]
        if not max(counts) <= attrs["any"] <= sum(counts):
            raise ValidationError({"any": "Must be a union of the three levels"})
        return attrs


class AliasEvidenceSerializer(_StrictSerializer):
    automatic_item_id = serializers.RegexField(rf"^(?:{GRAPH_ITEM_ID_PATTERN})$", required=False)
    candidate_item_ids = serializers.ListField(
        child=serializers.RegexField(rf"^(?:{GRAPH_ITEM_ID_PATTERN})$"), required=False
    )
    current_label = serializers.CharField(required=False, trim_whitespace=False)
    legacy_status = serializers.ChoiceField(choices=("unique", "ambiguous", "missing"), required=False)


class AliasIssueSerializer(_StrictSerializer):
    tag = serializers.CharField(trim_whitespace=False)
    target_item_id = serializers.RegexField(rf"^(?:{GRAPH_ITEM_ID_PATTERN})$", allow_null=True)
    last_known_label = serializers.CharField(allow_null=True, trim_whitespace=False)
    reason = serializers.ChoiceField(choices=CurationReviewItem.GENRE_ALIAS_REASONS)
    exposure = AliasExposureSerializer()
    evidence = AliasEvidenceSerializer()


class AliasReviewSerializer(_StrictSerializer):
    curation_exported_on = serializers.DateTimeField()
    issues = AliasIssueSerializer(many=True)
    targets = AliasTargetSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        for collection, key in (("targets", "id"), ("issues", "tag")):
            rows = attrs[collection]
            if len({row[key] for row in rows}) != len(rows):
                raise ValidationError({collection: f"Duplicate {key}"})
        return attrs


class UnresolvedGenreTagsReportSerializer(serializers.Serializer):
    unresolved_genre_tag_count = serializers.IntegerField(min_value=0)
    genre_alias_review = AliasReviewSerializer(required=False)


class ImportRunUnresolvedGenreTagsView(CurationView):
    """The pipeline's count of song genre tags its Gold stage couldn't match to a genre."""

    permission_classes = [IsPipelineOrAdmin]

    @transaction.atomic
    def post(self, request: Request) -> Response:
        serializer = UnresolvedGenreTagsReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = serializer.validated_data["unresolved_genre_tag_count"]
        review = serializer.validated_data.get("genre_alias_review")
        if review is not None:
            exported_on = review.pop("curation_exported_on")
            if not apply_alias_report(exported_on, review, count):
                return Response(status=status.HTTP_200_OK)
        run = ImportRun.objects.create(kind=ImportRun.Kind.UNRESOLVED_GENRE_TAGS, count=count)
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
