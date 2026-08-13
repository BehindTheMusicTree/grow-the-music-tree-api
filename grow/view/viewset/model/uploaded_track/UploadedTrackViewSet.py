from grow.filtering.set.uploaded_track.UploadedTrackFilterSet import UploadedTrackFilterSet
from grow.model.uploaded_track.UploadedTrack import UploadedTrack
from grow.serializer.model.uploaded_track.output.detailed import UploadedTrackDetailedSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class UploadedTrackViewSet(GrowModelViewSet[UploadedTrack]):
    def __init__(self, **kwargs):
        super().__init__(
            model_class=UploadedTrack,
            filterset_class=UploadedTrackFilterSet,
            simple_serializer_class=UploadedTrackDetailedSerializer,
            detailed_serializer_class=UploadedTrackDetailedSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def destroy(self, *args, **kwargs):
        return self._handle_destroy()
