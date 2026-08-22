from the_music_tree_genre_kit.view.viewset.genre.GenreExampleTreeMixin import GenreExampleTreeMixin

from grow.model.criteria.children.genre.Genre import Genre
from grow.view.viewset.model.criteria.CriteriaViewSet import CriteriaViewSet


class GenreViewSet(GenreExampleTreeMixin[Genre], CriteriaViewSet):
    def __init__(self, **kwargs):
        super().__init__(model_class=Genre, **kwargs)

    def on_example_tree_loaded(self, request) -> None:
        from grow.model.youtube_track.YoutubeTrack import YoutubeTrack

        YoutubeTrack.objects.filter(user=request.user).update(genre=None)
