from django.db.models import QuerySet
from the_music_tree_genre_kit.track.Fields import Fields as TrackFields

from grow.model.artist.Artist import Artist

from .Fields import Fields


class TrackConvenienceMixin:
    """
    Grow-only polymorphism conveniences for the kit's `Track`, shared by
    `UploadedTrack`/`YoutubeTrack`. Kept out of the kit since hear has a
    single concrete track type and never needs `resolve_concrete()`.
    """

    def resolve_concrete(self):
        youtube_track = getattr(self, Fields.YOUTUBE_TRACK_RELATED_NAME, None)
        if youtube_track is not None:
            return youtube_track
        uploaded_track = getattr(self, Fields.UPLOADED_TRACK_RELATED_NAME, None)
        if uploaded_track is not None:
            return uploaded_track
        return self

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
