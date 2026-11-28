from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.fields.json import KeyTransform
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from the_music_tree_api_kit.view.error.ApiErrorCode import ApiErrorCodeNumeric
from the_music_tree_api_kit.view.error.ErrorResponse import ErrorResponse
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination

from grow.bulk_import.BulkImportRun import GENRE_GRAPH_KIND
from grow.bulk_import.ImportAttempt import ImportAttempt
from grow.bulk_import.status import progress_payload
from grow.genre_graph.bulk_import.GenreGraphImportPayload import GenreGraphImportPayload
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from grow.pipeline_run.artists_recovery import (
    ACTIVE,
    RecoveryConflict,
    lock_recovery_admission,
    recovery_states,
    require_recovery,
)
from grow.pipeline_run.typical_durations import typical_stage_seconds
from grow.serializer.schema.common import PAGE_PARAMETERS
from grow.serializer.schema.runs import (
    ArtistsRecoveryExecutionSerializer,
    PipelineRunLatestSerializer,
    PipelineRunPageSerializer,
    PipelineRunSerializer,
)
from grow.view.curation import CurationView
from grow.view.permission.IsAdmin import IsAdmin
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin
from grow.view.pipeline_step_telemetry import StepTelemetrySerializer, check_chains_extend

Status = PipelineRunRequest.Status
Kind = PipelineRunRequest.Kind
Trigger = PipelineRunRequest.Trigger


def _serialize(run: PipelineRunRequest) -> dict[str, Any]:
    return {
        **{
            field: getattr(run, field)
            for field in (
                "uuid",
                "kind",
                "trigger",
                "status",
                "stage",
                "stage_current",
                "stage_total",
                "step_telemetry",
                "error",
                "requested_on",
                "started_on",
                "heartbeat_on",
                "finished_on",
            )
        },
        "requested_by": run.requested_by.email if run.requested_by else None,
        "cancel_requested": run.cancel_requested_on is not None,
        **(
            {
                "source_run_uuid": run.source_run.uuid,
                "manifest_sha256": run.source_run.manifest_sha256,
                "songs_snapshot_sha256": run.source_run.songs_snapshot_sha256,
            }
            if run.source_run_id is not None
            else {}
        ),
    }


def _is_bootstrap(attempt: ImportAttempt) -> bool | None:
    """Whether a graph import is the first one (no `expected_revision`); None for other kinds or a cleaned-up run."""
    if attempt.kind != GENRE_GRAPH_KIND:
        return None
    # Reads the one key in the database: the payload holds the whole graph and this runs on every poll.
    rows = list(
        GenreGraphImportPayload.objects.filter(run_id=attempt.run_id)
        .annotate(expected_revision=KeyTransform("expected_revision", "payload"))
        .values_list("expected_revision", flat=True)[:1]
    )
    if not rows:
        return None
    return rows[0] is None


def _active_import(run: PipelineRunRequest) -> dict[str, Any] | None:
    """The newest import attempt made for `run`, terminal or not: the front decides whether to show it."""
    if run.kind == Kind.SYNC_ARTISTS:
        attempt = (
            ImportAttempt.objects.filter(
                Q(pipeline_run_request_id=run.source_run_id) | Q(pipeline_run_request__source_run_id=run.source_run_id),
                kind="artists",
                user_id=None,
            )
            .order_by("-run_id", "-attempt")
            .first()
        )
    else:
        attempt = run.import_attempts.order_by("-queued_at", "-attempt").first()
    if attempt is None:
        return None
    return {**progress_payload(attempt), "bootstrap": _is_bootstrap(attempt)}


def _newest_first():
    return PipelineRunRequest.objects.select_related("requested_by", "source_run").order_by("-requested_on", "-pk")


def _conflict(message: str, api_error_code: ApiErrorCodeNumeric):
    return ErrorResponse.create_error_response(
        error_detail={"message": message, "code": "conflict"}, api_error_code=api_error_code
    )


def _not_running(run: PipelineRunRequest):
    return _conflict(f"The pipeline run is {run.status}", ApiErrorCodeNumeric.RESOURCE_INVALID_STATE)


class PipelineRunCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=PipelineRunRequest.Kind.choices)
    source_run_uuid = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if (attrs["kind"] == Kind.SYNC_ARTISTS) != ("source_run_uuid" in attrs):
            raise ValidationError({"source_run_uuid": "Required for sync_artists and disallowed for other kinds"})
        return attrs


class PipelineRunsView(CurationView):
    """Lists past runs (admin), or queues one for the pipeline's poller to claim.

    The origin comes from auth: an admin's request is `manual`, the pipeline key's is the `scheduled` nightly `full`.
    """

    def get_permissions(self):
        return [IsPipelineOrAdmin()] if self.request.method == "POST" else [IsAdmin()]

    @extend_schema(parameters=PAGE_PARAMETERS, responses=PipelineRunPageSerializer)
    def get(self, request: Request) -> Response:
        PipelineRunRequest.objects.expire_stale()
        paginator = AppPagination()
        page = paginator.paginate_queryset(_newest_first(), request, view=self)
        runs = page or []
        states = recovery_states(runs)
        return paginator.get_paginated_response(
            [{**_serialize(run), "artists_recovery": states.get(run.pk)} for run in runs]
        )

    @extend_schema(
        request=PipelineRunCreateSerializer,
        responses={
            status.HTTP_200_OK: PipelineRunSerializer,
            status.HTTP_201_CREATED: PipelineRunSerializer,
            status.HTTP_409_CONFLICT: OpenApiResponse(
                description="A pipeline run is already queued or running (api-kit error envelope)."
            ),
        },
    )
    def post(self, request: Request) -> Response:
        serializer = PipelineRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kind = serializer.validated_data["kind"]
        if kind == Kind.SYNC_ARTISTS and request.auth.role != "admin":
            raise PermissionDenied
        if request.auth.role == "pipeline":
            if kind != Kind.FULL:
                raise ValidationError({"kind": "The pipeline key may only request a full run"})
            origin = {"trigger": Trigger.SCHEDULED, "requested_by": None}
        else:
            origin = {"trigger": Trigger.MANUAL, "requested_by": request.user}
        if kind == Kind.CURATION and CurationSyncState.load().pending_count == 0:
            raise ValidationError({"pending_count": "No curation edit to apply"})
        PipelineRunRequest.objects.expire_stale()
        try:
            with transaction.atomic():
                lock_recovery_admission()
                if kind == Kind.SYNC_ARTISTS:
                    source_uuid = serializer.validated_data["source_run_uuid"]
                    source = get_object_or_404(PipelineRunRequest, uuid=source_uuid)
                    existing = PipelineRunRequest.objects.filter(source_run=source, status__in=ACTIVE).first()
                    if existing is not None:
                        return Response(_serialize(existing))
                    require_recovery(source)
                    origin["source_run"] = source
                run = PipelineRunRequest.objects.create(kind=kind, **origin)
        except IntegrityError:
            return _conflict("A pipeline run is already queued or running", ApiErrorCodeNumeric.RESOURCE_ALREADY_EXISTS)
        return Response(_serialize(run), status=status.HTTP_201_CREATED)


class PipelineRunLatestView(CurationView):
    permission_classes = [IsPipelineOrAdmin]

    @extend_schema(
        responses={
            status.HTTP_200_OK: PipelineRunLatestSerializer,
            status.HTTP_204_NO_CONTENT: OpenApiResponse(description="No run was ever requested."),
        },
        description="The newest run, with the progress of its linked import and typical stage durations.",
    )
    def get(self, request: Request) -> Response:
        PipelineRunRequest.objects.expire_stale()
        run = _newest_first().first()
        if run is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(
            {
                **_serialize(run),
                "active_import": _active_import(run),
                "typical_stage_seconds": typical_stage_seconds(run.kind),
            }
        )


class PipelineRunClaimView(CurationView):
    permission_classes = [IsPipelineOrAdmin]

    @extend_schema(
        request=None,
        responses={
            status.HTTP_200_OK: PipelineRunSerializer,
            status.HTTP_204_NO_CONTENT: OpenApiResponse(description="No queued run to claim."),
        },
    )
    def post(self, request: Request) -> Response:
        run = PipelineRunRequest.objects.claim()
        if run is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(_serialize(run))


class PipelineRunProgressSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=PipelineRunRequest.Stage.choices, required=False)
    stage_current = serializers.IntegerField(min_value=0, allow_null=True, required=False)
    stage_total = serializers.IntegerField(min_value=0, allow_null=True, required=False)
    step_telemetry = StepTelemetrySerializer(required=False)
    status = serializers.ChoiceField(choices=[Status.SUCCEEDED, Status.FAILED, Status.CANCELLED], required=False)
    error = serializers.CharField(allow_null=True, allow_blank=True, required=False)


class PipelineRunView(CurationView):
    """The poller's heartbeat, progress report and outcome for the request it claimed (an empty body is a heartbeat).

    The response's `cancelRequested` tells the poller to stop the run and report `cancelled`.
    """

    permission_classes = [IsPipelineOrAdmin]

    @extend_schema(
        request=PipelineRunProgressSerializer,
        responses={
            status.HTTP_200_OK: PipelineRunSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiResponse(description="No run has this uuid."),
            status.HTTP_409_CONFLICT: OpenApiResponse(description="The run is not running (api-kit error envelope)."),
        },
    )
    @transaction.atomic
    def patch(self, request: Request, uuid: str) -> Response:
        PipelineRunRequest.objects.expire_stale()
        run = get_object_or_404(PipelineRunRequest.objects.select_for_update(), uuid=uuid)
        if run.status != Status.RUNNING:
            return _not_running(run)
        serializer = PipelineRunProgressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if run.kind == Kind.SYNC_ARTISTS and data.get("status") == Status.SUCCEEDED:
            if request.auth.role != "pipeline":
                raise PermissionDenied
            require_recovery(run.source_run, finalize=True)
        if "step_telemetry" in data:
            if run.kind != Kind.FULL:
                raise ValidationError({"step_telemetry": "Step telemetry is only available for full runs"})
            update = data["step_telemetry"]
            telemetry = StepTelemetrySerializer(update).data
            check_chains_extend(run.step_telemetry, telemetry)
            run.step_telemetry = {
                "variant": None,
                "foreground": [],
                "wikidata": [],
                "wikidata_retry": None,
                **(run.step_telemetry or {}),
                **{key: telemetry[key] for key in update},
            }
            if run.step_telemetry["variant"] is None:
                raise ValidationError({"step_telemetry": "The first snapshot must specify the execution variant"})
        if "stage" in data:
            # A new stage starts with no progress unless the report carries it.
            run.stage_current = run.stage_total = None
        for field, value in data.items():
            if field != "step_telemetry":
                setattr(run, field, value)
        run.heartbeat_on = timezone.now()
        if "status" in data:
            run.finished_on = run.heartbeat_on
        run.save()
        return Response(_serialize(run))


class GoldFingerprintsSerializer(serializers.Serializer):
    manifest_sha_256 = serializers.RegexField(r"^[0-9a-f]{64}\Z", source="manifest_sha256", required=False)
    songs_snapshot_sha_256 = serializers.RegexField(r"^[0-9a-f]{64}\Z", source="songs_snapshot_sha256", required=False)
    artists_snapshot_sha_256 = serializers.RegexField(
        r"^[0-9a-f]{64}\Z", source="artists_snapshot_sha256", required=False
    )
    songs_run_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs):
        if ("manifest_sha256" in attrs) != ("songs_snapshot_sha256" in attrs):
            raise ValidationError("The manifest and songs fingerprints must be supplied together")
        if not attrs or attrs.keys() == {"songs_run_id"}:
            raise ValidationError("At least one snapshot fingerprint is required")
        return attrs


class PipelineGoldFingerprintsView(CurationView):
    permission_classes = [IsPipelineOrAdmin]

    @extend_schema(request=GoldFingerprintsSerializer, responses={204: None})
    @transaction.atomic
    def patch(self, request: Request, uuid: str) -> Response:
        if request.auth.role != "pipeline":
            raise PermissionDenied
        serializer = GoldFingerprintsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        songs_run_id = data.pop("songs_run_id", None)
        lock_recovery_admission()
        run = get_object_or_404(PipelineRunRequest.objects.select_for_update(), uuid=uuid)
        source = run
        if run.kind == Kind.SYNC_ARTISTS:
            if (
                run.status != Status.RUNNING
                or run.cancel_requested_on is not None
                or data.keys() != {"artists_snapshot_sha256"}
                or songs_run_id is not None
            ):
                raise RecoveryConflict(
                    "Seule l'empreinte du snapshot artistes peut être enregistrée pendant la reprise."
                )
            source = PipelineRunRequest.objects.select_for_update().get(pk=run.source_run_id)
            require_recovery(source)
        elif run.status != Status.RUNNING:
            if songs_run_id is None or data.keys() != {"manifest_sha256", "songs_snapshot_sha256"}:
                raise RecoveryConflict("L'attestation historique exige le numéro de l'import chansons.")
            if require_recovery(source, attest=True)["songs_run_id"] != songs_run_id:
                raise RecoveryConflict("L'import chansons ne correspond pas à la demande source.")
        elif songs_run_id is not None:
            raise ValidationError("A running source does not accept a historical attestation")
        for field, value in data.items():
            previous = getattr(source, field)
            if previous is not None and previous != value:
                raise RecoveryConflict("L'empreinte enregistrée ne correspond pas au fichier.")
            setattr(source, field, value)
        source.save(update_fields=data.keys())
        return Response(status=status.HTTP_204_NO_CONTENT)


class PipelineArtistsRecoveryView(CurationView):
    permission_classes = [IsPipelineOrAdmin]

    @extend_schema(responses=ArtistsRecoveryExecutionSerializer)
    def get(self, request: Request, uuid: str) -> Response:
        if request.auth.role != "pipeline":
            raise PermissionDenied
        run = get_object_or_404(
            PipelineRunRequest.objects.select_related("source_run"), uuid=uuid, kind=Kind.SYNC_ARTISTS
        )
        if run.status != Status.RUNNING:
            return _not_running(run)
        source = run.source_run
        return Response(
            {
                **require_recovery(source),
                "source_run_uuid": source.uuid,
                "manifest_sha256": source.manifest_sha256,
                "songs_snapshot_sha256": source.songs_snapshot_sha256,
                "artists_snapshot_sha256": source.artists_snapshot_sha256,
            }
        )


class PipelineRunCancelView(CurationView):
    """Cancels a queued request outright, or asks the poller to stop a running one."""

    @extend_schema(
        request=None,
        responses={
            status.HTTP_200_OK: PipelineRunSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiResponse(description="No run has this uuid."),
            status.HTTP_409_CONFLICT: OpenApiResponse(
                description="The run is neither queued nor running (api-kit error envelope)."
            ),
        },
    )
    @transaction.atomic
    def post(self, request: Request, uuid: str) -> Response:
        PipelineRunRequest.objects.expire_stale()
        run = get_object_or_404(PipelineRunRequest.objects.select_for_update(), uuid=uuid)
        if run.status not in (Status.QUEUED, Status.RUNNING):
            return _not_running(run)
        PipelineRunRequest.objects.request_cancel(run)
        return Response(_serialize(run))
