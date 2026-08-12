from typing import TYPE_CHECKING

from django.db import models
from the_music_tree_genre_kit.criteria.AbstractCriteria import AbstractCriteria

from grow.model.uploaded_track_mixin.UploadedTrackMixin import UploadedTrackMixin

from .CriteriaManager import CriteriaManager
from .Fields import Fields

if TYPE_CHECKING:
    from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
    from grow.model.uploaded_track.UploadedTrack import UploadedTrack


class Criteria(AbstractCriteria, UploadedTrackMixin):
    if TYPE_CHECKING:
        criteria_playlist: CriteriaPlaylist

    objects: CriteriaManager = CriteriaManager()

    @property
    def uploaded_tracks(self) -> models.QuerySet["UploadedTrack"]:
        return getattr(self, Fields.UPLOADED_TRACKS_RELATED_NAME)

    class Meta:
        db_table = "grow_criteria"
        verbose_name = "Criteria"
        verbose_name_plural = "Criterias"
        constraints = [
            models.CheckConstraint(condition=~models.Q(_name=""), name="%(class)s_non_empty_name"),
            models.UniqueConstraint(fields=[Fields.USER, Fields.NAME_INTERNAL], name="unique_name_per_user"),
        ]
        indexes = [
            models.Index(fields=[Fields.USER, Fields.NAME_INTERNAL], name="%(class)s_user_name_idx"),
            models.Index(fields=[Fields.USER, Fields.UUID], name="%(class)s_user_uuid_idx"),
        ]
