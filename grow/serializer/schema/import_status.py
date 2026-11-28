"""Wire shapes of the status responses for staged imports."""

from rest_framework import serializers

from grow.bulk_import.BulkImportRun import GENRE_GRAPH_KIND, GENRE_TREES_KIND, BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt
from grow.model.import_run.ImportRun import ImportRun


class ImportStepSerializer(serializers.Serializer):
    label = serializers.CharField()
    rowcount = serializers.IntegerField(allow_null=True)
    ms = serializers.IntegerField()


class ImportSqlActivitySerializer(serializers.Serializer):
    availability = serializers.ChoiceField(choices=["available", "unavailable"])
    session_present = serializers.BooleanField(required=False)
    state = serializers.CharField(required=False)
    query_age_seconds = serializers.FloatField(required=False, allow_null=True)
    wait_event_type = serializers.CharField(required=False, allow_null=True)
    blocker_count = serializers.IntegerField(required=False)


class ImportProgressSerializer(serializers.Serializer):
    run_id = serializers.IntegerField()
    task_id = serializers.CharField()
    kind = serializers.CharField()
    mode = serializers.ChoiceField(choices=BulkImportRun.Mode.choices)
    attempt = serializers.IntegerField()
    state = serializers.ChoiceField(choices=ImportAttempt.State.choices)
    queued_at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    step = serializers.CharField(allow_null=True)
    step_started_at = serializers.DateTimeField(allow_null=True)
    last_progress_at = serializers.DateTimeField(allow_null=True)
    heartbeat_at = serializers.DateTimeField(allow_null=True)
    completed_steps = ImportStepSerializer(many=True)
    data_applied = serializers.BooleanField()
    worker_absent_since = serializers.DateTimeField(allow_null=True)
    sql = ImportSqlActivitySerializer()
    observability_stale = serializers.BooleanField()


class ImportRunStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending", "success", "failed"])
    error = serializers.CharField(
        required=False, allow_null=True, help_text="Failure reason when the status is failed."
    )
    progress = ImportProgressSerializer(required=False, help_text="Merge progress for privileged callers.")


class RegionMapMergeResultSerializer(serializers.Serializer):
    imported = serializers.IntegerField()
    skipped = serializers.IntegerField()


class CatalogueMergeResultSerializer(RegionMapMergeResultSerializer):
    step_timings = ImportStepSerializer(many=True, required=False)


class GenreGraphMergeResultSerializer(serializers.Serializer):
    revision = serializers.UUIDField()
    membership_revision = serializers.UUIDField()


class GenreTreeMergeResultSerializer(serializers.Serializer):
    created_count = serializers.IntegerField()
    updated_count = serializers.IntegerField()
    deleted_count = serializers.IntegerField()
    dry_run = serializers.BooleanField()


class RegionMapImportRunStatusSerializer(ImportRunStatusSerializer):
    result = RegionMapMergeResultSerializer(required=False)


class CatalogueImportRunStatusSerializer(ImportRunStatusSerializer):
    result = CatalogueMergeResultSerializer(required=False)


class GenreGraphImportRunStatusSerializer(ImportRunStatusSerializer):
    result = GenreGraphMergeResultSerializer(required=False)


class GenreTreesImportRunStatusSerializer(ImportRunStatusSerializer):
    result = serializers.DictField(child=GenreTreeMergeResultSerializer(), required=False)


IMPORT_RUN_STATUS_SERIALIZERS = {
    ImportRun.Kind.REGION_MAP: RegionMapImportRunStatusSerializer,
    ImportRun.Kind.ARTISTS: CatalogueImportRunStatusSerializer,
    ImportRun.Kind.SONGS: CatalogueImportRunStatusSerializer,
    GENRE_GRAPH_KIND: GenreGraphImportRunStatusSerializer,
    GENRE_TREES_KIND: GenreTreesImportRunStatusSerializer,
}
