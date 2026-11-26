"""Output shapes of the hand-built `Response(...)` bodies of the service, import-run and pipeline-run views."""

from rest_framework import serializers

from grow.model.import_run.ImportRun import ImportRun
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from grow.serializer.schema.common import paginated_serializer


class HealthCheckEntrySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "warning", "error"])
    vendor = serializers.CharField(required=False, help_text="The database vendor.")
    message = serializers.CharField(required=False)


class HealthChecksSerializer(serializers.Serializer):
    database = HealthCheckEntrySerializer()
    cache = HealthCheckEntrySerializer()


class HealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["healthy", "unhealthy"])
    version = serializers.CharField()
    commit = serializers.CharField()
    uptime_seconds = serializers.IntegerField()
    checks = HealthChecksSerializer()


class AuthMeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["admin", "viewer", "pipeline", "curator"])
    email = serializers.EmailField(allow_null=True)


class PlaybackContextSerializer(serializers.Serializer):
    country = serializers.CharField(
        allow_null=True, help_text="The viewer's ISO 3166-1 alpha-2 country, when it can be told."
    )


class ImportRunSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ImportRun.Kind.choices)
    imported_on = serializers.DateTimeField()
    count = serializers.IntegerField()
    skipped_count = serializers.IntegerField(allow_null=True)


class ImportRunLatestSerializer(serializers.Serializer):
    """The newest run of each kind, `null` when the kind never ran."""

    global_tree = ImportRunSerializer(allow_null=True)
    regional_tree = ImportRunSerializer(allow_null=True)
    songs = ImportRunSerializer(allow_null=True)
    artists = ImportRunSerializer(allow_null=True)
    unresolved_genre_tags = ImportRunSerializer(allow_null=True)
    genealogy = ImportRunSerializer(allow_null=True)
    region_map = ImportRunSerializer(allow_null=True)


ImportRunPageSerializer = paginated_serializer("ImportRunPage", ImportRunSerializer)


class PipelineRunSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=PipelineRunRequest.Kind.choices)
    trigger = serializers.ChoiceField(choices=PipelineRunRequest.Trigger.choices)
    status = serializers.ChoiceField(choices=PipelineRunRequest.Status.choices)
    stage = serializers.ChoiceField(choices=PipelineRunRequest.Stage.choices, allow_null=True)
    stage_current = serializers.IntegerField(allow_null=True)
    stage_total = serializers.IntegerField(allow_null=True)
    step_telemetry = serializers.DictField(allow_null=True, help_text="`StepTelemetry` of a full run.")
    error = serializers.CharField(allow_null=True)
    requested_on = serializers.DateTimeField()
    started_on = serializers.DateTimeField(allow_null=True)
    heartbeat_on = serializers.DateTimeField(allow_null=True)
    finished_on = serializers.DateTimeField(allow_null=True)
    requested_by = serializers.EmailField(allow_null=True)
    cancel_requested = serializers.BooleanField()


class PipelineRunLatestSerializer(PipelineRunSerializer):
    active_import = serializers.JSONField(
        allow_null=True, help_text="Progress of the newest import attempt made for the run, plus `bootstrap`."
    )
    typical_stage_seconds = serializers.JSONField(
        allow_null=True, help_text="Median seconds per stage by telemetry chain over recent succeeded full runs."
    )


PipelineRunPageSerializer = paginated_serializer("PipelineRunPage", PipelineRunSerializer)
