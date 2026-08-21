from django.conf import settings
from django.db import models
from django.db.models import QuerySet
from the_music_tree_api_kit.field.AppCharField import AppCharField
from the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField import PrivateOneToOneField
from the_music_tree_genre_kit.track.Fields import Fields as TrackFields
from the_music_tree_genre_kit.track.Track import Track as KitTrack

from grow.model.artist.Artist import Artist
from grow.model.track.Fields import Fields
from grow.model.track.TrackManager import TrackManager


class YoutubeTrack(KitTrack):
    track = PrivateOneToOneField(
        KitTrack, on_delete=models.CASCADE, parent_link=True, related_name=Fields.YOUTUBE_TRACK_RELATED_NAME
    )
    youtube_video_id = AppCharField(
        max_length=settings.YOUTUBE_TRACK_VIDEO_ID_LEN_MAX, blank=True, null=True, default=None
    )

    objects: TrackManager[YoutubeTrack] = TrackManager()

    class Meta:
        db_table = "grow_youtube_track"
        verbose_name = "Youtube Track"
        verbose_name_plural = "Youtube Tracks"

    @property
    def relative_url(self) -> str:
        return f"library/youtube/{self.uuid}/"

    def __str__(self):
        position_str = f"#{self.track_number}" if self.track_number else "#--"

        artists: QuerySet[Artist] = self.artists.all()
        artists_str = (
            ", ".join(artist.name for artist in artists) if self.artists.exists() else f"[no {TrackFields.ARTISTS}]"
        )
        album_str = str(self.album) if self.album else f"[no {TrackFields.ALBUM}]"

        genre_str = f"{TrackFields.GENRE}: {self.genre}" if self.genre else f"{TrackFields.GENRE}: --"
        rating_str = f"{TrackFields.RATING}: {self.rating}" if self.rating else f"{TrackFields.RATING}: --"
        language_str = f"{TrackFields.LANGUAGE}: {self.language}" if self.language else f"{TrackFields.LANGUAGE}: --"

        return (
            f"{self.uuid} | {position_str} | '{self.title}' by {artists_str} | {album_str} | "
            f"{genre_str} | {rating_str} | {language_str} | " + f"{TrackFields.CREATED_ON}: {self.created_on}"
        )

    def simple_str(self) -> str:
        artists: QuerySet[Artist] = self.artists.all()
        artists_str = (
            ", ".join(artist.name for artist in artists) if self.artists.exists() else f"no {TrackFields.ARTISTS}"
        )
        return f"{self.uuid} | '{self.title}' by {artists_str}"

    @property
    def playlists(self) -> QuerySet:
        from grow.model.playlist.Playlist import Playlist

        return Playlist.objects.filter(track_playlist_rels__track=self)

    @property
    def playlists_with_positions(self) -> list[tuple[str, int]]:
        from grow.model.track_playlist_rel.TrackPlaylistRel import Fields as TrackPlaylistRelFields
        from grow.model.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

        track_playlist_rels = TrackPlaylistRel.objects.filter(user=self.user, track=self)
        return list(
            track_playlist_rels.values_list(TrackPlaylistRelFields.PLAYLIST + "__uuid", TrackPlaylistRelFields.POSITION)
        )
