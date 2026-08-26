from the_music_tree_genre_kit.view.viewset.track.SongExampleTreeMixin import SongExampleTreeMixin

from grow.filtering.set.youtube_track.YoutubeTrackFilterSet import YoutubeTrackFilterSet
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from grow.serializer.model.youtube_track.output.detailed import YoutubeTrackDetailedSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class YoutubeTrackViewSet(SongExampleTreeMixin[YoutubeTrack], GrowModelViewSet[YoutubeTrack]):
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
