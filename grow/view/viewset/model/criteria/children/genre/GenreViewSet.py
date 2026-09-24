import json

from django.conf import settings
from django.db import transaction
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from the_music_tree_api_kit.serializer.SerializerType import SerializerType
from the_music_tree_genre_kit.serializer.model.track.input.song_seed.Fields import (
    Fields as SongSeedFields,
)
from the_music_tree_genre_kit.serializer.model.track.input.song_seed.import_serializer import (
    SongSeedImportSerializer,
)
from the_music_tree_genre_kit.view.viewset.genre.GenreSeedTreeMixin import GenreSeedTreeMixin

from grow.model.criteria.children.genre.Genre import Genre
from grow.serializer.model.criteria.children.genre.input.post import GenrePostSerializer
from grow.serializer.model.criteria.children.genre.input.put import GenrePutSerializer
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin
from grow.view.viewset.model.criteria.CriteriaViewSet import CriteriaViewSet
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin


class GenreViewSet(HistoryActionMixin, GenreSeedTreeMixin[Genre], CriteriaViewSet):
    seed_songs_filename: str = "song_seed.json"

    def __init__(self, **kwargs):
        super().__init__(
            model_class=Genre,
            create_serializer_class=GenrePostSerializer,
            update_serializer_class=GenrePutSerializer,
            **kwargs,
        )

    @action(detail=False, methods=["post"], url_path="tree/load-seed")
    def load_seed_tree(self, request):
        with transaction.atomic():
            response = super().load_seed_tree(request)
            Genre.objects.assert_required_roots_present(request.user)

        return response

    @action(detail=False, methods=["post"], url_path="tree/import", permission_classes=[IsPipelineOrAdmin])
    def import_tree(self, request):
        with transaction.atomic():
            response = super().import_tree(request)
            Genre.objects.assert_required_roots_present(request.user)

        return response

    @action(detail=True, methods=["post"])
    def exclude(self, request: Request, *args, **kwargs) -> Response:
        instance = Genre.objects.exclude_instance(self.get_object(), **self._get_manager_write_kwargs(request))
        serializer = self._require_serializer(SerializerType.DETAILED)(instance=instance)
        return Response(data=serializer.data)

    def on_seed_tree_loaded(self, request) -> None:
        from grow.model.youtube_track.YoutubeTrack import YoutubeTrack

        data_path = settings.DATA_DIR / self.seed_songs_filename
        if not data_path.exists():
            raise FileNotFoundError(f"Seed songs file not found at {data_path}")

        with open(data_path) as f:
            data = json.load(f)

        serializer = SongSeedImportSerializer(data={SongSeedFields.SONGS: data})
        serializer.is_valid(raise_exception=True)

        YoutubeTrack.objects.import_seed_songs(request.user, serializer.validated_data[SongSeedFields.SONGS])
