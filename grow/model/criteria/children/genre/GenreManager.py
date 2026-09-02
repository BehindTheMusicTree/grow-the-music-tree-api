from typing import TYPE_CHECKING

from django.db import transaction
from the_music_tree_genre_kit.criteria.children.genre.AbstractGenreManager import AbstractGenreManager

from ...CriteriaManager import CriteriaManager

if TYPE_CHECKING:
    from .Genre import Genre


class GenreManager(AbstractGenreManager, CriteriaManager):
    model: Genre

    def _get_direct_tracks(self, instance: Genre) -> list:
        return list(instance.tracks.all())

    @transaction.atomic
    def create(self, **kwargs) -> Genre:
        # essential_tracks is a many-to-many field: it can't be passed to Model(**kwargs)
        # before the instance has a primary key, so it's set separately after creation.
        essential_tracks = kwargs.pop("essential_tracks", None)
        instance = super().create(**kwargs)
        if essential_tracks is not None:
            instance.essential_tracks.set(essential_tracks)
        return instance
