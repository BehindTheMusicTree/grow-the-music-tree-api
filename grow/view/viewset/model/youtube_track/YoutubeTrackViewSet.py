from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_q.tasks import async_task, fetch
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from the_music_tree_api_kit.private.get_request_owner import get_request_owner

from grow.filtering.set.youtube_track.YoutubeTrackFilterSet import YoutubeTrackFilterSet
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from grow.serializer.model.youtube_track.output.detailed import YoutubeTrackDetailedSerializer
from grow.track.bulk_import.merge import merge_song_import_run
from grow.track.bulk_import.part_loader import load_part
from grow.track.bulk_import.SongImportRun import SongImportRun
from grow.track.bulk_import.SongImportStaging import SongImportStaging
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin

IMPORT_RUNS = "songs/import-runs"


class YoutubeTrackViewSet(HistoryActionMixin, GrowModelViewSet[YoutubeTrack]):
    def __init__(self, **kwargs):
        super().__init__(
            model_class=YoutubeTrack,
            filterset_class=YoutubeTrackFilterSet,
            simple_serializer_class=YoutubeTrackDetailedSerializer,
            detailed_serializer_class=YoutubeTrackDetailedSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        # Songs without a video or a genre are stored for later linking, but aren't playable in the tree.
        return self._get_paginated_list_response(
            self.get_queryset().filter(youtube_video_id__isnull=False, genre__isnull=False)
        )

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def destroy(self, *args, **kwargs):
        return self._handle_destroy()

    @action(detail=False, methods=["post"], url_path=IMPORT_RUNS, permission_classes=[IsPipelineOrAdmin])
    def create_import_run(self, request):
        with transaction.atomic():
            # One sync at a time: a new run abandons every earlier one. A merge already running has copied its
            # staged rows into its own temp table, and a failed merge's rows would otherwise never be cleaned up.
            SongImportStaging.objects.all().delete()
            SongImportRun.objects.all().delete()
            run = SongImportRun.objects.create()
        return Response({"run_id": run.pk}, status=status.HTTP_201_CREATED)

    def _uncommitted_run(self, run_id: str) -> SongImportRun:
        run = get_object_or_404(SongImportRun, pk=run_id)
        if run.committed_on is not None:
            raise ValidationError("import run is already committed")
        return run

    @action(
        detail=False,
        methods=["put"],
        url_path=IMPORT_RUNS + r"/(?P<run_id>\d+)/parts/(?P<part>\d+)",
        permission_classes=[IsPipelineOrAdmin],
    )
    def upload_import_run_part(self, request, run_id: str, part: str):
        run = self._uncommitted_run(run_id)
        # The raw stream, not request.body: a part is far over DATA_UPLOAD_MAX_MEMORY_SIZE.
        count = load_part(run.pk, int(part), request._request)
        return Response({"count": count})

    @action(
        detail=False,
        methods=["post"],
        url_path=IMPORT_RUNS + r"/(?P<run_id>\d+)/commit",
        permission_classes=[IsPipelineOrAdmin],
    )
    def commit_import_run(self, request, run_id: str):
        run = self._uncommitted_run(run_id)
        if not SongImportRun.objects.filter(pk=run.pk, committed_on__isnull=True).update(committed_on=timezone.now()):
            raise ValidationError("import run is already committed")
        owner = get_request_owner(request)
        task_id = async_task(merge_song_import_run, run.pk, owner and owner.pk, request.auth.role == "pipeline")
        return Response({"task_id": task_id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["get"], url_path=r"songs/import/(?P<task_id>[^/.]+)/status")
    def import_songs_status(self, request, task_id=None):
        task = fetch(task_id)
        if task is None:
            return Response({"status": "pending"})
        if task.success:
            return Response({"status": "success", "result": task.result})
        return Response({"status": "failed", "error": str(task.result)})
