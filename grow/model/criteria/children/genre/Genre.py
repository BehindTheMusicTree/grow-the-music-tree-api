from django.conf import settings
from django.db import models
from the_music_tree_api_kit.field.foreign_key.PrivateManyToManyField import PrivateManyToManyField
from the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField import PrivateOneToOneField
from the_music_tree_genre_kit.criteria.children.genre.AbstractGenreCriteria import AbstractGenreCriteria
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks

from grow.model.track.Fields import Fields as TrackFields

from ...Criteria import Criteria
from .GenreManager import GenreManager


class Genre(AbstractGenreCriteria, Criteria):  # type: ignore[django-manager-missing]
    criteria_ptr = PrivateOneToOneField(Criteria, on_delete=models.CASCADE, parent_link=True, related_name="genre")
    essential_tracks = PrivateManyToManyField(
        settings.TRACK_MODEL, blank=True, related_name=TrackFields.ESSENTIAL_FOR_GENRES_RELATED_NAME
    )
    """Curated per-genre, not inherited from or propagated to subgenres."""

    objects: GenreManager = GenreManager()

    class Meta:
        db_table = "grow_genre"

    def save(self, *args, **kwargs):
        self.type = CriteriaType.objects.get(pk=CriteriaTypePks.GENRE)
        super().save(*args, **kwargs)
