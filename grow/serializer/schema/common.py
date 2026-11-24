"""Output shapes of hand-built `Response(...)` bodies, declared only so the OpenAPI schema can describe them."""

from rest_framework import serializers


class TaskIdSerializer(serializers.Serializer):
    task_id = serializers.CharField()


class ImportRunStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending", "success", "failed"])
    result = serializers.DictField(required=False, help_text="Merge counters, once the status is `success`.")
    error = serializers.CharField(required=False, help_text="Failure reason, once the status is `failed`.")
    progress = serializers.DictField(required=False, help_text="Merge progress, for privileged callers.")


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()
