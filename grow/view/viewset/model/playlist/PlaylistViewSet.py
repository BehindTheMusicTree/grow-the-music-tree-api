from the_music_tree_genre_kit.playlist.Fields import Fields as PlaylistFields
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.filtering.set.playlist.PlaylistFilterSet import PlaylistFilterSet
from grow.serializer.model.playlist.base.output.detailed import PlaylistDetailedSerializer
from grow.serializer.model.playlist.base.output.simple import PlaylistSimpleSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet


class PlaylistViewSet(GrowModelViewSet[Playlist]):
    def __init__(self, **kwargs):
        super().__init__(
            model_class=Playlist,
            filterset_class=PlaylistFilterSet,
            simple_serializer_class=PlaylistSimpleSerializer,
            detailed_serializer_class=PlaylistDetailedSerializer,
            **kwargs,
        )

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .prefetch_related(f"{PlaylistFields.TRACK_PLAYLIST_RELS_INTERNAL}__track__youtubetrack")
        )

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()
