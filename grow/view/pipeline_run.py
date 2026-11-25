from typing import Any

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from the_music_tree_api_kit.view.error.ApiErrorCode import ApiErrorCodeNumeric
from the_music_tree_api_kit.view.error.ErrorResponse import ErrorResponse
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination

from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from grow.serializer.schema.common import PAGE_PARAMETERS
from grow.serializer.schema.runs import PipelineRunPageSerializer, PipelineRunSerializer
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
    }


def _newest_first():
    return PipelineRunRequest.objects.select_related("requested_by").order_by("-requested_on", "-pk")


def _conflict(message: str, api_error_code: ApiErrorCodeNumeric):
    return ErrorResponse.create_error_response(
        error_detail={"message": message, "code": "conflict"}, api_error_code=api_error_code
    )


def _not_running(run: PipelineRunRequest):
    return _conflict(f"The pipeline run is {run.status}", ApiErrorCodeNumeric.RESOURCE_INVALID_STATE)


class PipelineRunCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=PipelineRunRequest.Kind.choices)


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
        return paginator.get_paginated_response([_serialize(run) for run in page or []])

    @extend_schema(
        request=PipelineRunCreateSerializer,
        responses={
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
                run = PipelineRunRequest.objects.create(kind=kind, **origin)
        except IntegrityError:
            return _conflict("A pipeline run is already queued or running", ApiErrorCodeNumeric.RESOURCE_ALREADY_EXISTS)
        return Response(_serialize(run), status=status.HTTP_201_CREATED)


class PipelineRunLatestView(CurationView):
    permission_classes = [IsPipelineOrAdmin]

    @extend_schema(
        responses={
            status.HTTP_200_OK: PipelineRunSerializer,
            status.HTTP_204_NO_CONTENT: OpenApiResponse(description="No run was ever requested."),
        }
    )
    def get(self, request: Request) -> Response:
        PipelineRunRequest.objects.expire_stale()
        run = _newest_first().first()
        if run is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(_serialize(run))


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


class PipelineRunCancelView(CurationView):
    """Cancels a queued request outright, or asks the poller to stop a running one."""

    @extend_schema(
        request=None,
        responses={
            status.HTTP_200_OK: PipelineRunSerializer,
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
