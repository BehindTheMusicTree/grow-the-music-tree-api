from typing import TYPE_CHECKING

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import QuerySet
from the_music_tree_api_kit.field.AppCharField import AppCharField
from the_music_tree_api_kit.field.foreign_key.PrivateForeignKey import PrivateForeignKey
from the_music_tree_api_kit.field.foreign_key.PrivateManyToManyField import PrivateManyToManyField

from grow.model.album.Album import Album
from grow.model.album.Fields import Fields as AlbumFields
from grow.model.artist.Artist import Artist
from grow.model.artist.Fields import Fields as ArtistFields
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Fields import Fields as CriteriaFields
from grow.model.playlist.Fields import Fields as PlayListFields
from grow.model.playlist.Playlist import Playlist
from grow.model.trackable_play_count.TrackablePlayCount import TrackablePlayCount

from .Fields import Fields
from .UploadedTrackManager import UploadedTrackManager

if TYPE_CHECKING:
    from grow.model.uploaded_track_playlist_rel.UploadedTrackPlaylistRel import UploadedTrackPlaylistRel


class UploadedTrack(TrackablePlayCount):
    title = AppCharField(max_length=settings.UPLOADED_TRACK_TITLE_LEN_MAX)
    artists = PrivateManyToManyField(Artist, blank=True, related_name=ArtistFields.UPLOADED_TRACKS_RELATED_NAME)
    album: Album = PrivateForeignKey(
        Album,  # type: ignore
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name=AlbumFields.UPLOADED_TRACKS_RELATED_NAME,
    )
    track_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(settings.UPLOADED_TRACK_TRACK_NUMBER_MAX)],
    )
    genre = PrivateForeignKey(
        Genre,
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name=CriteriaFields.UPLOADED_TRACKS_RELATED_NAME,
    )
    rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(settings.UPLOADED_TRACK_RATING_VALUE_MAX)],
    )
    language = AppCharField(max_length=settings.LANGUAGE_LEN_MAX, blank=True, default=None, null=True)
    archived = models.BooleanField(default=False)
    playlists = PrivateManyToManyField(
        Playlist, through="UploadedTrackPlaylistRel", related_name=PlayListFields.UPLOADED_TRACKS_RELATED_NAME
    )

    if TYPE_CHECKING:
        uploaded_track_playlist_rels: models.QuerySet[UploadedTrackPlaylistRel]

    objects: UploadedTrackManager = UploadedTrackManager()

    class Meta:
        db_table = "grow_uploaded_track"
        verbose_name = "Uploaded Track"
        verbose_name_plural = "Uploaded Tracks"
        indexes = [
            models.Index(fields=[Fields.USER, Fields.TITLE]),
            models.Index(fields=[Fields.USER, Fields.GENRE]),
            models.Index(fields=[Fields.USER, Fields.ALBUM]),
        ]

    @property
    def relative_url(self) -> str:
        return f"library/uploaded/{self.uuid}/"

    def __str__(self):
        position_str = f"#{self.track_number}" if self.track_number else "#--"

        artists: QuerySet[Artist] = self.artists.all()
        artists_str = (
            ", ".join(artist.name for artist in artists) if self.artists.exists() else f"[no {Fields.ARTISTS}]"
        )
        album_str = str(self.album) if self.album else f"[no {Fields.ALBUM}]"

        genre_str = f"{Fields.GENRE}: {self.genre}" if self.genre else f"{Fields.GENRE}: --"
        rating_str = f"{Fields.RATING}: {self.rating}" if self.rating else f"{Fields.RATING}: --"
        language_str = f"{Fields.LANGUAGE}: {self.language}" if self.language else f"{Fields.LANGUAGE}: --"

        return (
            f"{self.uuid} | {position_str} | '{self.title}' by {artists_str} | {album_str} | "
            f"{genre_str} | {rating_str} | {language_str} | " + f"{Fields.CREATED_ON}: {self.created_on}"
        )

    def simple_str(self) -> str:
        artists: QuerySet[Artist] = self.artists.all()
        artists_str = ", ".join(artist.name for artist in artists) if self.artists.exists() else f"no {Fields.ARTISTS}"
        return f"{self.uuid} | '{self.title}' by {artists_str}"

    @property
    def playlists_with_positions(self) -> list[tuple[str, int]]:
        from grow.model.uploaded_track_playlist_rel.UploadedTrackPlaylistRel import (
            Fields as UploadedTrackPlaylistRelFields,
        )
        from grow.model.uploaded_track_playlist_rel.UploadedTrackPlaylistRel import UploadedTrackPlaylistRel

        uploaded_track_playlist_rels = UploadedTrackPlaylistRel.objects.filter(user=self.user, uploaded_track=self)
        return list(
            uploaded_track_playlist_rels.values_list(
                UploadedTrackPlaylistRelFields.PLAYLIST + "__uuid", UploadedTrackPlaylistRelFields.POSITION
            )
        )
