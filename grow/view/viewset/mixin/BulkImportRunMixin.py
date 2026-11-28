import json
import shutil
import tempfile
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import IO, Any

from django.conf import settings
from django.db import models, transaction
from django.http import UnreadablePostError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_q.models import Task
from django_q.tasks import async_task
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, PermissionDenied, ValidationError
from rest_framework.response import Response
from the_music_tree_api_kit.private.get_request_owner import get_request_owner

from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.copy_part import copy_part
from grow.bulk_import.ImportAttempt import ImportAttempt
from grow.bulk_import.lifecycle import queue_attempt
from grow.bulk_import.manifests import record_part, require_complete_parts
from grow.bulk_import.merge_lock import claim_lost_merge
from grow.bulk_import.status import progress_payload, reconcile
from grow.genre_music.source_gate import lock_catalogue_sources
from grow.model.import_run.ImportRun import ImportRun
from grow.openapi.documents import object_schema
from grow.openapi.ndjson import ASSIGNMENT_ROW, UUID, part_row
from grow.pipeline_run.artists_recovery import (
    ARTISTS,
    SONGS,
    Kind,
    RecoveryConflict,
    guard_catalogue_import,
    lock_active_recovery,
    lock_recovery_admission,
)
from grow.pipeline_run.link import HEADER_PARAMETER, linked_pipeline_run
from grow.serializer.schema.artist import ArtistImportRunCreateRequestSerializer
from grow.serializer.schema.common import (
    CountSerializer,
    FullImportRunCreateRequestSerializer,
    ImportRunCreatedSerializer,
    ImportRunCreateRequestSerializer,
    TaskIdSerializer,
)
from grow.serializer.schema.import_status import IMPORT_RUN_STATUS_SERIALIZERS
from grow.serializer.schema.song import SongImportRunCreateRequestSerializer
from grow.track.bulk_import.assignment_part_loader import load_part as load_assignment_part
from grow.track.bulk_import.contract import (
    require_complete_run,
    require_declared_part,
    require_reviewed_contract,
    run_metadata,
)
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin

GROUP_PREFIX = "import-run-"
SPOOL_MEMORY_BYTES = 8 * 1024 * 1024

_RUN_ID_PARAM = OpenApiParameter("run_id", int, OpenApiParameter.PATH)
_PART_PARAM = OpenApiParameter("part", int, OpenApiParameter.PATH)


def _upload_schema(description: str, parameters: list[OpenApiParameter], item_schema: dict[str, Any]) -> Callable:
    return extend_schema(
        request={"application/x-ndjson": OpenApiTypes.BINARY},
        extensions={"x-ndjson-item-schema": item_schema},
        parameters=parameters,
        responses=CountSerializer,
        description=description,
    )


def assignment_part_upload_action(url_prefix: str) -> Callable:
    @_upload_schema(
        "One gzip NDJSON part of the run's genre assignments.", [_RUN_ID_PARAM, _PART_PARAM], ASSIGNMENT_ROW
    )
    @action(
        detail=False,
        methods=["put"],
        url_path=url_prefix + r"import-runs/(?P<run_id>\d+)/assignments/parts/(?P<part>\d+)",
        permission_classes=[IsPipelineOrAdmin],
    )
    def upload_assignment_part(self, request, run_id: str, part: str):
        def get_run(*, lock=False):
            runs = BulkImportRun.objects.select_for_update() if lock else BulkImportRun.objects.all()
            run = get_object_or_404(runs, pk=run_id, kind=ImportRun.Kind.SONGS)
            if run.committed_on is not None:
                raise ValidationError("import run is already committed")
            if run.expected_parts is None:
                raise ValidationError("Assignments require a semantic import run with reviewed revisions")
            require_declared_part(run, "assignments", int(part))
            return run

        get_run()
        with spooled_body(request) as body, transaction.atomic():
            run = get_run(lock=True)
            count = load_assignment_part(run.pk, int(part), body)
            record_part(run=run, stream="assignments", part=int(part), count=count, body=body)
        return Response({"count": count})

    return upload_assignment_part


def spooled_body(request) -> IO[bytes]:
    """
    The whole request body in a seekable file. Loading straight from the raw stream (a part is far over
    DATA_UPLOAD_MAX_MEMORY_SIZE, so not `request.body`) would run its COPY while the client is still sending, and a
    slow upload would trip the web `statement_timeout`. A body cut short is a client error (400), not a server one.
    """
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES)
    try:
        try:
            shutil.copyfileobj(request._request, spool)
        except UnreadablePostError as e:
            raise ParseError("upload interrupted before the body was complete") from e
        expected = request.META.get("CONTENT_LENGTH")
        if expected:
            if not expected.isdigit():
                raise ParseError("invalid Content-Length header")
            if spool.tell() != int(expected):
                raise ParseError(f"upload interrupted: received {spool.tell()} of {expected} bytes")
    except BaseException:
        spool.close()
        raise
    spool.seek(0)
    return spool


def enqueue_merge(merge: Callable[..., dict[str, int]], run: BulkImportRun, attempt: ImportAttempt) -> None:
    try:
        async_task(merge, run.pk, run.user_id, run.record, group=attempt.task_id, attempt_id=attempt.pk)
    except Exception:
        ImportAttempt.objects.filter(pk=attempt.pk, state=ImportAttempt.State.QUEUED).update(
            state=ImportAttempt.State.FAILED,
            error="Could not enqueue import; see API logs",
            finished_at=timezone.now(),
        )
        raise


def import_run_status_action(
    url_prefix: str, kind: str, merge: Callable[..., dict[str, int]], name: str = "import_run_status"
) -> Callable:
    """
    The poll action of a `kind`'s import runs: the latest attempt's state, or the legacy django-q task of `merge`.
    `name` must be the attribute it is bound to on the viewset: DRF reads the handler name when `@action` runs.
    """

    def import_run_status(self, request, task_id=None):
        privileged = request.auth is not None and request.auth.role in {"admin", "pipeline"}
        attempt = ImportAttempt.objects.filter(task_id=task_id, kind=kind, user_id=None).order_by("-attempt").first()
        if attempt is not None:
            if not privileged:
                if attempt.state == ImportAttempt.State.SUCCEEDED:
                    return Response({"status": "success", "result": attempt.result})
                if attempt.state in {ImportAttempt.State.FAILED, ImportAttempt.State.INTERRUPTED}:
                    return Response({"status": "failed", "error": "Import failed"})
                return Response({"status": "pending"})
            retry = reconcile(attempt)
            if retry is not None:
                run = BulkImportRun.objects.get(pk=retry.run_id)
                enqueue_merge(merge, run, retry)
                return Response({"status": "pending", "progress": progress_payload(retry)})
            attempt = (
                ImportAttempt.objects.filter(task_id=task_id, kind=kind, user_id=None).order_by("-attempt").first()
            )
            payload = {"status": "pending", "progress": progress_payload(attempt)}
            if attempt.state == ImportAttempt.State.SUCCEEDED:
                payload.update(status="success", result=attempt.result)
            elif attempt.state in {ImportAttempt.State.FAILED, ImportAttempt.State.INTERRUPTED}:
                payload.update(status="failed", error=attempt.error)
            return Response(payload)
        # Retain the legacy task contract, scoped to this endpoint's merge function.
        task = Task.objects.filter(group=task_id).order_by("-stopped").first()
        if task is not None and task.func != f"{merge.__module__}.{merge.__name__}":
            task = None
        if task is None:
            if privileged and task_id.startswith(GROUP_PREFIX) and task_id[len(GROUP_PREFIX) :].isdigit():
                lost = claim_lost_merge(int(task_id[len(GROUP_PREFIX) :]), kind)
                if lost is not None:
                    attempt = queue_attempt(lost)
                    enqueue_merge(merge, lost, attempt)
            return Response({"status": "pending"})
        if task.success:
            return Response({"status": "success", "result": task.result})
        return Response({"status": "failed", "error": str(task.result) if privileged else "Import failed"})

    import_run_status.__name__ = name
    bound = action(
        detail=False,
        methods=["get"],
        url_path=url_prefix + r"import/(?P<task_id>[^/.]+)/status",
        url_name=name.replace("_", "-"),
    )(import_run_status)
    return extend_schema(
        parameters=[OpenApiParameter("task_id", str, OpenApiParameter.PATH)],
        responses=IMPORT_RUN_STATUS_SERIALIZERS[kind],
    )(bound)


def bulk_import_run_actions(
    url_prefix: str,
    kind: str,
    staging_model: type[models.Model],
    load_part: Callable[[int, int, IO[bytes]], int],
    merge: Callable[[int, int | None, bool], dict[str, int]],
    deletion_key: str,
    modes: tuple[str, ...] = tuple(BulkImportRun.Mode.values),
    *,
    extra_staging_models: tuple[type[models.Model], ...] = (),
) -> tuple[Callable, ...]:
    """
    The bulk import-run protocol actions for one `kind`, to unpack into a viewset body: create a run, upload its
    gzip NDJSON parts, commit it (queues `merge`), poll the merge task. Every path starts with `url_prefix`.
    `modes` lists the run modes `kind` accepts. A `delta` run also uploads its deleted ids (gzip NDJSON,
    `{deletion_key: <uuid>}` per line) to `deletions/`.
    """
    runs = f"{url_prefix}import-runs"
    if kind == ImportRun.Kind.SONGS:
        create_request: type = SongImportRunCreateRequestSerializer
    elif kind == ARTISTS:
        create_request = ArtistImportRunCreateRequestSerializer
    elif BulkImportRun.Mode.DELTA in modes:
        create_request = ImportRunCreateRequestSerializer
    else:
        create_request = FullImportRunCreateRequestSerializer

    def deletion_row(line_number: int, line: bytes) -> tuple:
        try:
            return (str(uuid.UUID(json.loads(line)[deletion_key])),)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ValidationError(f"line {line_number}: {deletion_key} must be a UUID ({e})") from e

    def uncommitted_run(run_id: str, *, lock: bool = False) -> BulkImportRun:
        runs = BulkImportRun.objects.select_for_update() if lock else BulkImportRun.objects.all()
        run = get_object_or_404(runs, pk=run_id, kind=kind)
        if run.committed_on is not None:
            raise ValidationError("import run is already committed")
        return run

    @extend_schema(
        request=create_request,
        parameters=[HEADER_PARAMETER],
        responses={status.HTTP_201_CREATED: ImportRunCreatedSerializer},
        description=f"Accepted modes: {', '.join(modes)}. Abandons every uncommitted run of the same kind.",
    )
    @action(detail=False, methods=["post"], url_path=runs, permission_classes=[IsPipelineOrAdmin])
    def create_import_run(self, request):
        mode = request.data.get("mode", BulkImportRun.Mode.FULL)
        if mode not in modes:
            raise ValidationError(f"mode must be one of {', '.join(modes)}")
        pipeline_run = linked_pipeline_run(request, allow_artists_recovery=kind == ARTISTS)
        metadata = run_metadata(request.data, mode) if kind == ImportRun.Kind.SONGS else {}
        with transaction.atomic():
            if kind == SONGS:
                lock_catalogue_sources()
            if kind in (SONGS, ARTISTS):
                lock_recovery_admission()
                guard_catalogue_import(kind, pipeline_run, mode=mode)
            if kind == SONGS:
                require_reviewed_contract(metadata)
            if pipeline_run is not None and pipeline_run.kind == Kind.SYNC_ARTISTS:
                if request.auth.role != "pipeline":
                    raise PermissionDenied
                parts = request.data.get("expected_parts")
                if (
                    not isinstance(parts, dict)
                    or parts.keys() != {"artists"}
                    or type(parts["artists"]) is not int
                    or parts["artists"] < 1
                ):
                    raise ValidationError('expected_parts must declare {"artists": <number of parts>}')
                metadata["expected_parts"] = parts
                existing = BulkImportRun.objects.filter(
                    kind=ARTISTS,
                    committed_on=None,
                    pipeline_run_request__source_run_id=pipeline_run.source_run_id,
                ).first()
                if existing is not None:
                    if existing.expected_parts != parts:
                        raise RecoveryConflict("Le nombre de parties diffère de l'import artistes déjà préparé.")
                    return Response({"run_id": existing.pk}, status=status.HTTP_201_CREATED)
            elif kind == ARTISTS and "expected_parts" in request.data:
                raise ValidationError("expected_parts is reserved for artists recovery")
            # A new run abandons every uncommitted one of its kind, and every committed one older than twice the task
            # timeout: django-q kills a timed-out merge without running its cleanup, so its rows would leak. Twice,
            # because committed_on is the enqueue time and a run can wait one full merge in the single-worker queue
            # before its own starts; a younger committed run's rows stay until its queued merge drops them.
            merge_deadline = timezone.now() - timedelta(seconds=2 * settings.Q_CLUSTER["timeout"])
            abandoned = BulkImportRun.objects.filter(kind=kind).filter(
                models.Q(committed_on__isnull=True) | models.Q(committed_on__lt=merge_deadline)
            )
            # Uploads and commit hold the same row lock. Evaluate the population once after waiting,
            # so cleanup cannot miss an upload committed while this request was waiting.
            abandoned_ids = list(abandoned.select_for_update().order_by("pk").values_list("pk", flat=True))
            for model in (staging_model, *extra_staging_models):
                model._default_manager.filter(run_id__in=abandoned_ids).delete()
            BulkImportDeletion.objects.filter(run_id__in=abandoned_ids).delete()
            BulkImportRun.objects.filter(pk__in=abandoned_ids).delete()
            run = BulkImportRun.objects.create(kind=kind, mode=mode, pipeline_run_request=pipeline_run, **metadata)
        return Response({"run_id": run.pk}, status=status.HTTP_201_CREATED)

    @_upload_schema(
        "One gzip NDJSON part of the run's rows.",
        [_RUN_ID_PARAM, _PART_PARAM, *([HEADER_PARAMETER] if kind == ARTISTS else [])],
        part_row(kind),
    )
    @action(
        detail=False,
        methods=["put"],
        url_path=runs + r"/(?P<run_id>\d+)/parts/(?P<part>\d+)",
        permission_classes=[IsPipelineOrAdmin],
    )
    def upload_import_run_part(self, request, run_id: str, part: str):
        uncommitted_run(run_id)
        with spooled_body(request) as body, transaction.atomic():
            run = uncommitted_run(run_id, lock=True)
            index = int(part)
            stream = "artists" if kind == ARTISTS else "songs"
            if (
                kind == ARTISTS
                and (linked := run.pipeline_run_request) is not None
                and linked.kind == Kind.SYNC_ARTISTS
            ):
                lock_active_recovery(recovery_import_request(request, linked.source_run_id))
                if run.expected_parts is None or index >= run.expected_parts["artists"]:
                    raise ValidationError("Part is outside the run's declared import streams")
            require_declared_part(run, stream, index)
            count = load_part(run.pk, index, body)
            if run.expected_parts is not None:
                record_part(run=run, stream=stream, part=index, count=count, body=body)
        return Response({"count": count})

    @(
        _upload_schema(
            f'Delta runs only: the deleted ids, gzip NDJSON with one `{{"{deletion_key}": <uuid>}}` per line.',
            [_RUN_ID_PARAM],
            object_schema({deletion_key: UUID}, closed=False),
        )
        if BulkImportRun.Mode.DELTA in modes
        else extend_schema(exclude=True)
    )
    @action(
        detail=False,
        methods=["put"],
        url_path=runs + r"/(?P<run_id>\d+)/deletions",
        permission_classes=[IsPipelineOrAdmin],
    )
    def upload_import_run_deletions(self, request, run_id: str):
        run = uncommitted_run(run_id)
        if run.mode != BulkImportRun.Mode.DELTA:
            raise ValidationError("deletions are only accepted by a delta import run")
        with spooled_body(request) as body, transaction.atomic():
            run = uncommitted_run(run_id, lock=True)
            require_declared_part(run, "deletions", 0)
            count = copy_part(BulkImportDeletion, ("musicbrainz_id",), deletion_row, run.pk, 0, body)
            if run.expected_parts is not None:
                record_part(run=run, stream="deletions", part=0, count=count, body=body)
        return Response({"count": count})

    @extend_schema(
        request=None,
        parameters=[_RUN_ID_PARAM, *([HEADER_PARAMETER] if kind == ARTISTS else [])],
        responses={status.HTTP_202_ACCEPTED: TaskIdSerializer},
        description="Queues the merge; poll its status with the returned task id.",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path=runs + r"/(?P<run_id>\d+)/commit",
        permission_classes=[IsPipelineOrAdmin],
    )
    def commit_import_run(self, request, run_id: str):
        owner = get_request_owner(request)
        user_id, record = owner and owner.pk, request.auth.role == "pipeline"
        with transaction.atomic():
            if kind == SONGS:
                lock_catalogue_sources()
            if kind in (SONGS, ARTISTS):
                lock_recovery_admission()
            if kind == ARTISTS:
                attempt = (
                    ImportAttempt.objects.filter(
                        run_id=run_id, kind=ARTISTS, pipeline_run_request__kind=Kind.SYNC_ARTISTS
                    )
                    .select_related("pipeline_run_request")
                    .order_by("-attempt")
                    .first()
                )
                if attempt is not None:
                    recovery = recovery_import_request(request, attempt.pipeline_run_request.source_run_id)
                    guard_catalogue_import(kind, recovery, mode=attempt.mode, submitted=True)
                    return Response({"task_id": attempt.task_id}, status=status.HTTP_202_ACCEPTED)
            run = uncommitted_run(run_id, lock=True)
            if kind in (SONGS, ARTISTS):
                linked = run.pipeline_run_request
                if linked is not None and linked.kind == Kind.SYNC_ARTISTS:
                    linked = recovery_import_request(request, linked.source_run_id)
                guard_catalogue_import(kind, linked, mode=run.mode)
                run.pipeline_run_request = linked
            require_complete_run(run)
            if kind == ARTISTS and linked is not None and linked.kind == Kind.SYNC_ARTISTS:
                if run.expected_parts is None:
                    raise ValidationError("Artists recovery requires declared import parts")
                require_complete_parts(run, {"artists": (staging_model, run.expected_parts["artists"])})
            if kind == SONGS:
                require_reviewed_contract(
                    {"graph_revision": run.graph_revision, "membership_revision": run.membership_revision}
                )
            if not BulkImportRun.objects.filter(pk=run.pk, committed_on__isnull=True).update(
                committed_on=timezone.now(),
                user_id=user_id,
                record=record,
                pipeline_run_request_id=run.pipeline_run_request_id,
            ):
                raise ValidationError("import run is already committed")
            run.user_id, run.record = user_id, record
            attempt = queue_attempt(run)
        enqueue_merge(merge, run, attempt)
        return Response({"task_id": attempt.task_id}, status=status.HTTP_202_ACCEPTED)

    return (
        create_import_run,
        upload_import_run_part,
        upload_import_run_deletions,
        commit_import_run,
        import_run_status_action(url_prefix, kind, merge),
    )


def recovery_import_request(request, source_id):
    if request.auth.role != "pipeline":
        raise PermissionDenied
    recovery = linked_pipeline_run(request, allow_artists_recovery=True)
    if recovery is None or recovery.kind != Kind.SYNC_ARTISTS or recovery.source_run_id != source_id:
        raise RecoveryConflict("La demande de reprise active doit être fournie et correspondre à la source.")
    return recovery
