import uuid
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
    from grow.model.artist_alias.ArtistAlias import ArtistAlias
    from grow.model.artist_link.ArtistLink import ArtistLink
    from grow.model.artist_membership.ArtistMembership import ArtistMembership

# MusicBrainz's special-purpose artists (https://musicbrainz.org/doc/Style/Unknown_and_untitled/Special_purpose_artist),
# placeholders without a page of their own. Mirrors SPECIAL_PURPOSE_ARTIST_IDS in the-music-tree-pipelines'
# gold/src/gold/artist_export.py: keep the two in sync.
SPECIAL_PURPOSE_ARTIST_MBIDS = frozenset(
    uuid.UUID(mbid)
    for mbid in (
        "89ad4ac3-39f7-470e-963a-56509c546377",  # Various Artists
        "125ec42a-7229-4250-afc5-e057484327fe",  # [unknown]
        "f731ccc4-e22a-43af-a747-64213329e088",  # [anonymous]
        "9be7f096-97ec-4615-8957-8d40b5dcbc41",  # [traditional]
        "eec63d3c-3b81-4ad4-b1e4-7c147d4d2b61",  # [no artist]
        "33cf029c-63b0-41a0-9855-be2a3665fb3b",  # [data]
        "314e1c25-dde7-4e4d-b2f4-0a7b9f7c56dc",  # [dialogue]
        "66ea0139-149f-4a0c-8fbf-5ea9ec4a6e49",  # [Disney]
        "c06aa285-520e-40c0-b776-83d2c9e8a6d1",  # Deleted Artist
    )
)


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
    disambiguation = models.TextField(null=True, blank=True)
    # Songs crediting the artist, playable or not, kept by the songs import merge to rank search results.
    recording_count = models.PositiveIntegerField(db_default=0)

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_special_purpose(self) -> bool:
        return self.musicbrainz_artist_id in SPECIAL_PURPOSE_ARTIST_MBIDS

    if TYPE_CHECKING:
        albums: models.QuerySet[Album]
        members: models.QuerySet[ArtistMembership]
        member_of: models.QuerySet[ArtistMembership]
        links: models.QuerySet[ArtistLink]
        aliases: models.QuerySet[ArtistAlias]

    objects: ArtistManager = ArtistManager()

    @property
    def tracks(self) -> models.QuerySet[Track]:
        return getattr(self, Fields.TRACKS_RELATED_NAME)

    class Meta:
        db_table = "grow_artist"
        constraints = [models.CheckConstraint(condition=~models.Q(_name=""), name="artist_non_empty_name")]

    def __str__(self) -> str:
        return f"{self.uuid} | {self._name}"
