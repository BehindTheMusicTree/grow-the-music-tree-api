from abc import abstractmethod
from typing import TYPE_CHECKING

from django.db import models
from the_music_tree_api_kit.private_unique_resource.PrivateUniqueResource import PrivateUniqueResource

from .Fields import Fields

if TYPE_CHECKING:
    from grow.model.uploaded_track.UploadedTrack import UploadedTrack


class UploadedTrackMixin(PrivateUniqueResource):
    class Meta:
        abstract = True

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def uploaded_tracks(self) -> models.QuerySet["UploadedTrack"]:
        pass

    @property
    @abstractmethod
    def uploaded_tracks_not_archived(self) -> models.QuerySet["UploadedTrack"]:
        return self.uploaded_tracks.filter(archived=False)

    @property
    def uploaded_tracks_not_archived_sorted(self) -> models.QuerySet["UploadedTrack"]:
        return self.uploaded_tracks_not_archived.order_by(f"-{Fields.CREATED_ON}")

    @property
    def uploaded_tracks_not_archived_count(self) -> int:
        return self.uploaded_tracks_not_archived.count()

    @property
    def uploaded_tracks_archived_count(self) -> int:
        return self.uploaded_tracks.filter(archived=True).count()
