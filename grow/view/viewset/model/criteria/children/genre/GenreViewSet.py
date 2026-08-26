import json

from django.conf import settings
from the_music_tree_genre_kit.serializer.model.track.input.song_example.Fields import (
    Fields as SongExampleFields,
)
from the_music_tree_genre_kit.serializer.model.track.input.song_example.import_serializer import (
    SongExampleImportSerializer,
)
from the_music_tree_genre_kit.view.viewset.genre.GenreExampleTreeMixin import GenreExampleTreeMixin

from grow.model.criteria.children.genre.Genre import Genre
from grow.view.viewset.model.criteria.CriteriaViewSet import CriteriaViewSet


class GenreViewSet(GenreExampleTreeMixin[Genre], CriteriaViewSet):
    example_songs_filename: str = "song_example.json"

    def __init__(self, **kwargs):
        super().__init__(model_class=Genre, **kwargs)

    def on_example_tree_loaded(self, request) -> None:
        from grow.model.youtube_track.YoutubeTrack import YoutubeTrack

        data_path = settings.DATA_DIR / self.example_songs_filename
        if not data_path.exists():
            raise FileNotFoundError(f"Example songs file not found at {data_path}")

        with open(data_path) as f:
            data = json.load(f)

        serializer = SongExampleImportSerializer(data={SongExampleFields.SONGS: data})
        serializer.is_valid(raise_exception=True)

        YoutubeTrack.objects.import_example_songs(request.user, serializer.validated_data[SongExampleFields.SONGS])
