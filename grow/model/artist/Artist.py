from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from the_music_tree_api_kit.field.AppCharField import AppCharField

from grow.model.track_mixin.TrackMixin import TrackMixin

from .ArtistManager import ArtistManager
from .Fields import Fields

if TYPE_CHECKING:
    from the_music_tree_genre_kit.track.Track import Track

    from grow.model.album.Album import Album


class Artist(TrackMixin):
    _name = AppCharField(max_length=settings.ARTIST_NAME_LEN_MAX, default=None, db_column=Fields.NAME_PUBLIC)

    @property
    def name(self) -> str:
        return self._name

    if TYPE_CHECKING:
        albums: models.QuerySet[Album]

    objects: ArtistManager = ArtistManager()

    @property
    def tracks(self) -> models.QuerySet[Track]:
        return getattr(self, Fields.TRACKS_RELATED_NAME)

    class Meta:
        db_table = "grow_artist"
        constraints = [models.CheckConstraint(condition=~models.Q(_name=""), name="artist_non_empty_name")]

    def __str__(self) -> str:
        return f"{self.uuid} | {self._name}"
