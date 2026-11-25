"""Output shapes of hand-built `Response(...)` bodies, declared only so the OpenAPI schema can describe them."""

from typing import Any

from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers

from grow.bulk_import.BulkImportRun import BulkImportRun


class TaskIdSerializer(serializers.Serializer):
    task_id = serializers.CharField()


class ImportRunStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending", "success", "failed"])
    result = serializers.DictField(required=False, help_text="Merge counters, once the status is `success`.")
    error = serializers.CharField(required=False, help_text="Failure reason, once the status is `failed`.")
    progress = serializers.DictField(required=False, help_text="Merge progress, for privileged callers.")


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


class ImportRunCreateRequestSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=BulkImportRun.Mode.choices,
        required=False,
        help_text="Defaults to `full`. A `delta` run carries only changed rows plus a deletions upload.",
    )


class FullImportRunCreateRequestSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=[BulkImportRun.Mode.FULL], required=False, help_text="Only `full` runs are accepted."
    )


class ImportRunCreatedSerializer(serializers.Serializer):
    run_id = serializers.IntegerField()


class CountSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Rows loaded from the uploaded body.")


def paginated_serializer(
    name: str, item: type[serializers.Serializer], **extra: serializers.Field
) -> type[serializers.Serializer]:
    """`AppPagination`'s envelope, for an `APIView` that paginates by hand (spectacular only wraps viewset lists)."""
    fields: dict[str, Any] = {
        "overall_total": serializers.IntegerField(),
        "next": serializers.URLField(allow_null=True),
        "previous": serializers.URLField(allow_null=True),
        "results": item(many=True),
        "page": serializers.IntegerField(),
        "page_size": serializers.IntegerField(),
        "total_pages": serializers.IntegerField(),
        **extra,
    }
    return type(name, (serializers.Serializer,), fields)


PAGE_PARAMETERS = [
    OpenApiParameter("page", int, required=False, description="1-based page number."),
    OpenApiParameter("page_size", int, required=False, description="Rows per page, capped by the server."),
]
