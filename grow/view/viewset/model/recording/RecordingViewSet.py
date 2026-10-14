from grow.filtering.set.recording.RecordingFilterSet import RecordingFilterSet
from grow.model.import_run.ImportRun import ImportRun
from grow.model.recording.Recording import Recording
from grow.serializer.model.recording.output.detailed import RecordingDetailedSerializer
from grow.track.bulk_import.merge import merge_song_import_run
from grow.track.bulk_import.part_loader import load_part
from grow.track.bulk_import.SongImportStaging import SongImportStaging
from grow.view.pagination.OptionalTotalPagination import OptionalTotalPagination, wants_no_total
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet
from grow.view.viewset.mixin.BulkImportRunMixin import bulk_import_run_actions
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin


class RecordingViewSet(HistoryActionMixin, GrowModelViewSet[Recording]):
    pagination_class = OptionalTotalPagination

    def __init__(self, **kwargs):
        super().__init__(
            model_class=Recording,
            filterset_class=RecordingFilterSet,
            simple_serializer_class=RecordingDetailedSerializer,
            detailed_serializer_class=RecordingDetailedSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        # Genreless songs are stored for later linking but have no place in the tree.
        queryset = self.get_queryset().filter(genre__isnull=False)
        if wants_no_total(self.request):
            # pk order lets Postgres stop at the first page instead of sorting the whole genre subtree.
            queryset = queryset.order_by("pk")
        return self._get_paginated_list_response(queryset)

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def destroy(self, *args, **kwargs):
        return self._handle_destroy()

    create_import_run, upload_import_run_part, commit_import_run, import_run_status = bulk_import_run_actions(
        "songs/", ImportRun.Kind.SONGS, SongImportStaging, load_part, merge_song_import_run
    )


class LegacyYoutubeViewSet(RecordingViewSet):
    def list(self, *args, **kwargs):
        # Legacy consumers require a non-null youtubeVideoId.
        queryset = self.get_queryset().filter(genre__isnull=False, youtube_video_id__isnull=False)
        return self._get_paginated_list_response(queryset)
