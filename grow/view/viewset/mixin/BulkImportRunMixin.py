from collections.abc import Callable
from datetime import timedelta
from typing import IO

from django.conf import settings
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_q.tasks import async_task, fetch
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from the_music_tree_api_kit.private.get_request_owner import get_request_owner

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.model.import_run.ImportRun import ImportRun
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin


def bulk_import_run_actions(
    url_prefix: str,
    kind: ImportRun.Kind,
    staging_model: type[models.Model],
    load_part: Callable[[int, int, IO[bytes]], int],
    merge: Callable[[int, int | None, bool], dict[str, int]],
) -> tuple[Callable, ...]:
    """
    The bulk import-run protocol actions for one `kind`, to unpack into a viewset body: create a run, upload its
    gzip NDJSON parts, commit it (queues `merge`), poll the merge task. Every path starts with `url_prefix`.
    """
    runs = f"{url_prefix}import-runs"

    def uncommitted_run(run_id: str) -> BulkImportRun:
        run = get_object_or_404(BulkImportRun, pk=run_id, kind=kind)
        if run.committed_on is not None:
            raise ValidationError("import run is already committed")
        return run

    @action(detail=False, methods=["post"], url_path=runs, permission_classes=[IsPipelineOrAdmin])
    def create_import_run(self, request):
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
            abandoned.delete()
            run = BulkImportRun.objects.create(kind=kind)
        return Response({"run_id": run.pk}, status=status.HTTP_201_CREATED)

    @action(
        detail=False,
        methods=["put"],
        url_path=runs + r"/(?P<run_id>\d+)/parts/(?P<part>\d+)",
        permission_classes=[IsPipelineOrAdmin],
    )
    def upload_import_run_part(self, request, run_id: str, part: str):
        run = uncommitted_run(run_id)
        # The raw stream, not request.body: a part is far over DATA_UPLOAD_MAX_MEMORY_SIZE.
        count = load_part(run.pk, int(part), request._request)
        return Response({"count": count})

    @action(
        detail=False,
        methods=["post"],
        url_path=runs + r"/(?P<run_id>\d+)/commit",
        permission_classes=[IsPipelineOrAdmin],
    )
    def commit_import_run(self, request, run_id: str):
        run = uncommitted_run(run_id)
        if not BulkImportRun.objects.filter(pk=run.pk, committed_on__isnull=True).update(committed_on=timezone.now()):
            raise ValidationError("import run is already committed")
        owner = get_request_owner(request)
        task_id = async_task(merge, run.pk, owner and owner.pk, request.auth.role == "pipeline")
        return Response({"task_id": task_id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["get"], url_path=url_prefix + r"import/(?P<task_id>[^/.]+)/status")
    def import_run_status(self, request, task_id=None):
        task = fetch(task_id)
        if task is None:
            return Response({"status": "pending"})
        if task.success:
            return Response({"status": "success", "result": task.result})
        return Response({"status": "failed", "error": str(task.result)})

    return create_import_run, upload_import_run_part, commit_import_run, import_run_status
