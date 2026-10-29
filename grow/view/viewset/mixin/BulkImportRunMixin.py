import json
import shutil
import tempfile
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import IO

from django.conf import settings
from django.db import models, transaction
from django.http import UnreadablePostError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_q.models import Task
from django_q.tasks import async_task
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.response import Response
from the_music_tree_api_kit.private.get_request_owner import get_request_owner

from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.copy_part import copy_part
from grow.bulk_import.merge_lock import claim_lost_merge
from grow.model.import_run.ImportRun import ImportRun
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin

GROUP_PREFIX = "import-run-"
SPOOL_MEMORY_BYTES = 8 * 1024 * 1024


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


def bulk_import_run_actions(
    url_prefix: str,
    kind: ImportRun.Kind,
    staging_model: type[models.Model],
    load_part: Callable[[int, int, IO[bytes]], int],
    merge: Callable[[int, int | None, bool], dict[str, int]],
    deletion_key: str,
    modes: tuple[str, ...] = tuple(BulkImportRun.Mode.values),
) -> tuple[Callable, ...]:
    """
    The bulk import-run protocol actions for one `kind`, to unpack into a viewset body: create a run, upload its
    gzip NDJSON parts, commit it (queues `merge`), poll the merge task. Every path starts with `url_prefix`.
    `modes` lists the run modes `kind` accepts. A `delta` run also uploads its deleted ids (gzip NDJSON,
    `{deletion_key: <uuid>}` per line) to `deletions/`.
    """
    runs = f"{url_prefix}import-runs"

    def deletion_row(line_number: int, line: bytes) -> tuple:
        try:
            return (str(uuid.UUID(json.loads(line)[deletion_key])),)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ValidationError(f"line {line_number}: {deletion_key} must be a UUID ({e})") from e

    def uncommitted_run(run_id: str) -> BulkImportRun:
        run = get_object_or_404(BulkImportRun, pk=run_id, kind=kind)
        if run.committed_on is not None:
            raise ValidationError("import run is already committed")
        return run

    @action(detail=False, methods=["post"], url_path=runs, permission_classes=[IsPipelineOrAdmin])
    def create_import_run(self, request):
        mode = request.data.get("mode", BulkImportRun.Mode.FULL)
        if mode not in modes:
            raise ValidationError(f"mode must be one of {', '.join(modes)}")
        with transaction.atomic():
            # A new run abandons every uncommitted one of its kind, and every committed one older than twice the task
            # timeout: django-q kills a timed-out merge without running its cleanup, so its rows would leak. Twice,
            # because committed_on is the enqueue time and a run can wait one full merge in the single-worker queue
            # before its own starts; a younger committed run's rows stay until its queued merge drops them.
            merge_deadline = timezone.now() - timedelta(seconds=2 * settings.Q_CLUSTER["timeout"])
            abandoned = BulkImportRun.objects.filter(kind=kind).filter(
                models.Q(committed_on__isnull=True) | models.Q(committed_on__lt=merge_deadline)
            )
            staging_model._default_manager.filter(run_id__in=abandoned.values("pk")).delete()
            BulkImportDeletion.objects.filter(run_id__in=abandoned.values("pk")).delete()
            abandoned.delete()
            run = BulkImportRun.objects.create(kind=kind, mode=mode)
        return Response({"run_id": run.pk}, status=status.HTTP_201_CREATED)

    @action(
        detail=False,
        methods=["put"],
        url_path=runs + r"/(?P<run_id>\d+)/parts/(?P<part>\d+)",
        permission_classes=[IsPipelineOrAdmin],
    )
    def upload_import_run_part(self, request, run_id: str, part: str):
        run = uncommitted_run(run_id)
        with spooled_body(request) as body:
            count = load_part(run.pk, int(part), body)
        return Response({"count": count})

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
        with spooled_body(request) as body:
            count = copy_part(BulkImportDeletion, ("musicbrainz_id",), deletion_row, run.pk, 0, body)
        return Response({"count": count})

    @action(
        detail=False,
        methods=["post"],
        url_path=runs + r"/(?P<run_id>\d+)/commit",
        permission_classes=[IsPipelineOrAdmin],
    )
    def commit_import_run(self, request, run_id: str):
        run = uncommitted_run(run_id)
        owner = get_request_owner(request)
        user_id, record = owner and owner.pk, request.auth.role == "pipeline"
        if not BulkImportRun.objects.filter(pk=run.pk, committed_on__isnull=True).update(
            committed_on=timezone.now(), user_id=user_id, record=record
        ):
            raise ValidationError("import run is already committed")
        task_id = f"{GROUP_PREFIX}{run.pk}"
        async_task(merge, run.pk, user_id, record, group=task_id)
        return Response({"task_id": task_id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["get"], url_path=url_prefix + r"import/(?P<task_id>[^/.]+)/status")
    def import_run_status(self, request, task_id=None):
        task = Task.objects.filter(group=task_id).order_by("-stopped").first()
        if task is None:
            if task_id.startswith(GROUP_PREFIX) and task_id[len(GROUP_PREFIX) :].isdigit():
                lost = claim_lost_merge(int(task_id[len(GROUP_PREFIX) :]), kind)
                if lost is not None:
                    async_task(merge, lost.pk, lost.user_id, lost.record, group=task_id)
            return Response({"status": "pending"})
        if task.success:
            return Response({"status": "success", "result": task.result})
        return Response({"status": "failed", "error": str(task.result)})

    return create_import_run, upload_import_run_part, upload_import_run_deletions, commit_import_run, import_run_status
