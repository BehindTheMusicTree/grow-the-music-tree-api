from django.conf import settings
from django.db import models
from the_music_tree_api_kit.exception.validation.app.AppValidationException import AppValidationException
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode
from the_music_tree_api_kit.field.foreign_key.PrivateManyToManyField import PrivateManyToManyField
from the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField import PrivateOneToOneField
from the_music_tree_genre_kit.criteria.children.genre.AbstractGenreCriteria import AbstractGenreCriteria
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide
from the_music_tree_genre_kit.criteria.Fields import Fields
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks

from grow.model.track.Fields import Fields as TrackFields

from ...Criteria import Criteria
from .GenreManager import REQUIRED_ROOT_GENRE_NAMES, GenreManager


class Genre(AbstractGenreCriteria, Criteria):  # type: ignore[django-manager-missing]
    criteria_ptr = PrivateOneToOneField(Criteria, on_delete=models.CASCADE, parent_link=True, related_name="genre")
    essential_songs = PrivateManyToManyField(
        settings.TRACK_MODEL, blank=True, related_name=TrackFields.ESSENTIAL_FOR_GENRES_RELATED_NAME
    )
    """Curated per-genre, not inherited from or propagated to subgenres."""

    objects: GenreManager = GenreManager()

    class Meta:
        db_table = "grow_genre"

    def save(self, *args, **kwargs):
        self.type = CriteriaType.objects.get(pk=CriteriaTypePks.GENRE)
        super().save(*args, **kwargs)

    def _validate_side_placement(self) -> None:
        """Also runs per node on import, where `root` is the in-memory planned root."""
        super()._validate_side_placement()
        if self.side != CriteriaSide.POP:
            return
        root = self.root
        if root.parent_id is None and root.name in REQUIRED_ROOT_GENRE_NAMES:
            raise AppValidationException(
                field_name=Fields.SIDE,
                message="side is not applicable under the Mainstream Pop root",
                field_validation_error_code=FieldValidationErrorCode.REFERENCE_INVALID,
            )
