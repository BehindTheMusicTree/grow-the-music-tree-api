import json
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from the_music_tree_api_kit.private.get_request_owner import get_request_owner
from the_music_tree_genre_graph import GenreGraph, GraphValidationError
from the_music_tree_genre_kit.genre_graph.assignments import assignment_snapshot
from the_music_tree_genre_kit.genre_graph.models import (
    GenreGraphAssignmentState,
    GenreGraphAttributionRevision,
    GenreGraphDataset,
)
from the_music_tree_genre_kit.genre_graph.storage import (
    GraphRevisionConflict,
    effective_attributions,
    graph_read_transaction,
    tracks_needing_refinement,
)

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.authentication.GoogleIdTokenAuthentication import GoogleIdTokenAuthentication
from grow.bulk_import.BulkImportRun import GENRE_GRAPH_KIND, BulkImportRun
from grow.bulk_import.lifecycle import queue_attempt
from grow.genre_graph.bulk_import.GenreGraphImportPayload import GenreGraphImportPayload
from grow.genre_graph.bulk_import.merge import merge_reference_graph_import_run
from grow.genre_graph.service import (
    DATASET_KEY,
    import_reference_graph,
    reference_dataset,
    restore_initial_assignments,
    restore_reference_graph,
    restore_song_attributions,
    write_song_attributions,
)
from grow.model.song.Song import Song
from grow.pipeline_run.link import HEADER_PARAMETER, linked_pipeline_run
from grow.serializer.schema.common import DetailSerializer, TaskIdSerializer
from grow.serializer.schema.genre_graph import (
    GraphAssignmentTokensSerializer,
    GraphTokensSerializer,
    ReferenceGraphSerializer,
    SongAttributionsSerializer,
)
from grow.view.permission.IsCuratorOrAdmin import IsCuratorOrAdmin
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin
from grow.view.viewset.mixin.BulkImportRunMixin import enqueue_merge


class GraphInput(serializers.Serializer):
    def get_fields(self):
        fields = super().get_fields()
        for name, public_name in (
            ("expected_revision", "expectedRevision"),
            ("expected_assignment_revision", "expectedAssignmentRevision"),
            ("expected_membership_revision", "expectedMembershipRevision"),
        ):
            if name in fields:
                field = fields.pop(name)
                field.source = name
                fields[public_name] = field
        return fields


class GraphImportInput(GraphInput):
    graph = serializers.DictField()
    mapping = serializers.DictField(child=serializers.UUIDField(allow_null=True))
    expected_revision = serializers.UUIDField(allow_null=True)
    retirements = serializers.DictField(child=serializers.DictField(), required=False)


class GraphRestoreInput(GraphInput):
    revision = serializers.UUIDField()
    expected_revision = serializers.UUIDField()
    retirements = serializers.DictField(child=serializers.DictField(), required=False)


class AttributionInput(GraphInput):
    attributions = serializers.DictField(child=serializers.ListField(child=serializers.DictField(), allow_empty=False))
    expected_assignment_revision = serializers.UUIDField(allow_null=True)
    expected_revision = serializers.UUIDField()
    expected_membership_revision = serializers.UUIDField()


class AttributionRestoreInput(GraphInput):
    expected_assignment_revision = serializers.UUIDField(allow_null=True)
    revision = serializers.UUIDField()
    expected_revision = serializers.UUIDField()
    expected_membership_revision = serializers.UUIDField()


class InitialAssignmentsRestoreInput(GraphInput):
    revision = serializers.UUIDField()
    expected_revision = serializers.UUIDField()
    expected_membership_revision = serializers.UUIDField()
    provenance = serializers.DictField()


def _assignment_token(dataset, song_id):
    revision = (
        GenreGraphAssignmentState.objects.filter(dataset=dataset, track_id=song_id)
        .values_list("revision", flat=True)
        .first()
    )
    return {"assignmentRevision": str(revision) if revision is not None else None}


def _tokens(dataset):
    return {"revision": str(dataset.revision), "membershipRevision": str(dataset.membership_revision)}


class GraphView(APIView):
    authentication_classes = [GoogleIdTokenAuthentication, ApiKeyAuthentication]
    # Semantic identities and provenance keys are opaque contract data.
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def handle_exception(self, exc):
        if isinstance(exc, GraphRevisionConflict):
            return Response({"detail": str(exc)}, status=409)
        if isinstance(exc, GraphValidationError):
            return Response({"detail": str(exc)}, status=400)
        return super().handle_exception(exc)


class ReferenceGraphView(GraphView):
    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsPipelineOrAdmin()]

    @extend_schema(responses=ReferenceGraphSerializer)
    def get(self, request):
        reference_dataset()
        with graph_read_transaction(key=DATASET_KEY, with_payload=True) as dataset:
            mapping = dict(dataset.nodes.filter(is_active=True).values_list("identity", "grow_criteria__pk"))
            if any(pk is None for pk in mapping.values()):
                raise GraphValidationError("Reference graph contains unbound identities")
            return Response(
                {**_tokens(dataset), "graph": dataset.payload, "mapping": {key: str(pk) for key, pk in mapping.items()}}
            )

    @extend_schema(request=GraphImportInput, responses=GraphTokensSerializer)
    @transaction.atomic
    def put(self, request):
        serializer = GraphImportInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        dataset = import_reference_graph(
            payload=data["graph"],
            mapping=data["mapping"],
            expected_revision=data["expected_revision"],
            curation_exported_on=data["graph"].get("curationExportedOn"),
            retirements=data.get("retirements"),
        )
        return Response(_tokens(dataset))


class ReferenceGraphImportRunsView(GraphView):
    """
    Queues a reference graph import (same body as `PUT genres/graph/`) and answers 202 `{taskId}`; the merge runs in the
    worker, so the initial cutover over every song is not bound by the web `statement_timeout`. The checks here only
    fail fast: the worker repeats them under its locks.
    """

    permission_classes = [IsPipelineOrAdmin]

    @extend_schema(
        request=GraphImportInput,
        parameters=[HEADER_PARAMETER],
        responses={status.HTTP_202_ACCEPTED: TaskIdSerializer, status.HTTP_409_CONFLICT: DetailSerializer},
    )
    def post(self, request):
        serializer = GraphImportInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        GenreGraph(data["graph"])
        expected = data["expected_revision"]
        current = GenreGraphDataset.objects.filter(pk=DATASET_KEY).values_list("revision", flat=True).first()
        if current != expected:
            raise GraphRevisionConflict("Reference graph revision changed; reload before importing")
        owner = get_request_owner(request)
        pipeline_run = linked_pipeline_run(request)
        body = {
            "graph": data["graph"],
            "mapping": {key: str(value) if value is not None else None for key, value in data["mapping"].items()},
            "expected_revision": str(expected) if expected is not None else None,
            "retirements": data.get("retirements"),
        }
        with transaction.atomic():
            if connection.vendor == "postgresql":
                # Serialize concurrent POSTs: the exists() check below takes no row lock.
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [GENRE_GRAPH_KIND])
            # Drop the runs of an earlier merge django-q killed without cleanup (see bulk_import_run_actions).
            stale = BulkImportRun.objects.filter(
                kind=GENRE_GRAPH_KIND,
                committed_on__lt=timezone.now() - timedelta(seconds=2 * settings.Q_CLUSTER["timeout"]),
            )
            GenreGraphImportPayload.objects.filter(run_id__in=stale.values("pk")).delete()
            stale.delete()
            # A finished run (success or failure) is deleted by its merge, so a remaining one is queued or running.
            if BulkImportRun.objects.filter(kind=GENRE_GRAPH_KIND).exists():
                return Response({"detail": "A graph import is already running"}, status=status.HTTP_409_CONFLICT)
            run = BulkImportRun.objects.create(
                kind=GENRE_GRAPH_KIND,
                committed_on=timezone.now(),
                user_id=owner and owner.pk,
                record=False,
                pipeline_run_request=pipeline_run,
            )
            GenreGraphImportPayload.objects.create(run_id=run.pk, payload=json.loads(json.dumps(body)))
            attempt = queue_attempt(run)
        enqueue_merge(merge_reference_graph_import_run, run, attempt)
        return Response({"taskId": attempt.task_id}, status=status.HTTP_202_ACCEPTED)


class ReferenceGraphRestoreView(GraphView):
    permission_classes = [IsCuratorOrAdmin]

    @extend_schema(request=GraphRestoreInput, responses=GraphTokensSerializer)
    def post(self, request):
        serializer = GraphRestoreInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_tokens(restore_reference_graph(**serializer.validated_data)))


class InitialAssignmentsRestoreView(GraphView):
    permission_classes = [IsCuratorOrAdmin]

    @extend_schema(request=InitialAssignmentsRestoreInput, responses=GraphTokensSerializer)
    def post(self, request):
        serializer = InitialAssignmentsRestoreInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_tokens(restore_initial_assignments(**serializer.validated_data)))


class SongAttributionsView(GraphView):
    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsCuratorOrAdmin()]

    @extend_schema(responses=SongAttributionsSerializer)
    def get(self, request, song_id):
        reference_dataset()
        with graph_read_transaction(key=DATASET_KEY) as dataset:
            song = get_object_or_404(Song, pk=song_id, user__isnull=True)
            direct = assignment_snapshot(dataset=dataset, track_id=song.pk)
            effective = list(
                effective_attributions(key=DATASET_KEY)
                .filter(track_id=song_id)
                .order_by("node__identity")
                .values_list("node__identity", flat=True)
            )
            return Response(
                {
                    **_tokens(dataset),
                    "attributions": direct,
                    **_assignment_token(dataset, song_id),
                    "effectiveAttributions": effective,
                    "needsRefinement": tracks_needing_refinement(
                        Song.objects.filter(pk=song_id), key=DATASET_KEY
                    ).exists(),
                }
            )

    @extend_schema(request=AttributionInput, responses=GraphAssignmentTokensSerializer)
    @transaction.atomic
    def put(self, request, song_id):
        get_object_or_404(Song, pk=song_id, user__isnull=True)
        reference_dataset()
        serializer = AttributionInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        dataset = write_song_attributions(song_id=song_id, **serializer.validated_data)
        return Response({**_tokens(dataset), **_assignment_token(dataset, song_id)})


class SongAttributionsRestoreView(GraphView):
    permission_classes = [IsCuratorOrAdmin]

    @extend_schema(request=AttributionRestoreInput, responses=GraphAssignmentTokensSerializer)
    @transaction.atomic
    def post(self, request, song_id):
        get_object_or_404(Song, pk=song_id, user__isnull=True)
        reference_dataset()
        serializer = AttributionRestoreInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        get_object_or_404(
            GenreGraphAttributionRevision, dataset_id=DATASET_KEY, track_id=song_id, revision=data["revision"]
        )
        dataset = restore_song_attributions(song_id=song_id, **data)
        return Response({**_tokens(dataset), **_assignment_token(dataset, song_id)})
