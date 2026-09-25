from django_q.tasks import async_task, fetch
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from the_music_tree_api_kit.private.get_request_owner import get_request_owner
from the_music_tree_genre_kit.serializer.model.track.input.song_seed.entry_serializer import (
    SongSeedEntrySerializer,
)
from the_music_tree_genre_kit.view.viewset.track.SongSeedTreeMixin import SongSeedTreeMixin

from grow.filtering.set.youtube_track.YoutubeTrackFilterSet import YoutubeTrackFilterSet
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from grow.serializer.model.youtube_track.output.detailed import YoutubeTrackDetailedSerializer
from grow.track.tasks import run_import_seed_songs
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin


class YoutubeTrackViewSet(HistoryActionMixin, SongSeedTreeMixin[YoutubeTrack], GrowModelViewSet[YoutubeTrack]):
    def __init__(self, **kwargs):
        super().__init__(
            model_class=YoutubeTrack,
            filterset_class=YoutubeTrackFilterSet,
            simple_serializer_class=YoutubeTrackDetailedSerializer,
            detailed_serializer_class=YoutubeTrackDetailedSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def destroy(self, *args, **kwargs):
        return self._handle_destroy()

    @action(detail=False, methods=["post"], url_path="songs/import", permission_classes=[IsPipelineOrAdmin])
    def import_songs(self, request):
        serializer = SongSeedEntrySerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        owner = get_request_owner(request)
        task_id = async_task(run_import_seed_songs, owner and owner.pk, serializer.validated_data)
        return Response({"task_id": task_id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["get"], url_path=r"songs/import/(?P<task_id>[^/.]+)/status")
    def import_songs_status(self, request, task_id=None):
        task = fetch(task_id)
        if task is None:
            return Response({"status": "pending"})
        if task.success:
            return Response({"status": "success", "result": task.result})
        return Response({"status": "failed", "error": str(task.result)})
