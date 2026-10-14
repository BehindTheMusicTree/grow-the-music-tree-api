from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from the_music_tree_api_kit.field.AppCharField import AppCharField
from the_music_tree_genre_kit.track_mixin.TrackMixin import TrackMixin

from .ArtistManager import ArtistManager
from .Fields import Fields

if TYPE_CHECKING:
    from the_music_tree_genre_kit.track.Track import Track

    from grow.model.album.Album import Album
    from grow.model.artist_link.ArtistLink import ArtistLink
    from grow.model.artist_membership.ArtistMembership import ArtistMembership


class Artist(TrackMixin):
    class Type(models.TextChoices):
        PERSON = "person"
        GROUP = "group"
        ORCHESTRA = "orchestra"
        CHOIR = "choir"
        CHARACTER = "character"
        OTHER = "other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="%(class)ss", null=True, blank=True
    )

    _name = AppCharField(max_length=settings.ARTIST_NAME_LEN_MAX, default=None, db_column=Fields.NAME_PUBLIC)

    musicbrainz_artist_id = models.UUIDField(null=True, blank=True, unique=True)
    type = models.TextField(choices=Type.choices, null=True, blank=True)
    country = models.CharField(max_length=2, null=True, blank=True)
    begin_year = models.SmallIntegerField(null=True, blank=True)
    end_year = models.SmallIntegerField(null=True, blank=True)
    ended = models.BooleanField(default=False)

    @property
    def name(self) -> str:
        return self._name

    if TYPE_CHECKING:
        albums: models.QuerySet[Album]
        members: models.QuerySet[ArtistMembership]
        member_of: models.QuerySet[ArtistMembership]
        links: models.QuerySet[ArtistLink]

    objects: ArtistManager = ArtistManager()

    @property
    def tracks(self) -> models.QuerySet[Track]:
        return getattr(self, Fields.TRACKS_RELATED_NAME)

    class Meta:
        db_table = "grow_artist"
        constraints = [models.CheckConstraint(condition=~models.Q(_name=""), name="artist_non_empty_name")]

    def __str__(self) -> str:
        return f"{self.uuid} | {self._name}"
