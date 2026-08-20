from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Case, F, Value, When
from the_music_tree_api_kit.base.save_context import SaveContext
from the_music_tree_api_kit.field.foreign_key.PrivateForeignKey import PrivateForeignKey
from the_music_tree_api_kit.private_standard_resource.PrivateStandardResource import PrivateStandardResource

from grow.model.playlist.Fields import Fields as PlayListFields
from grow.model.playlist.Playlist import Playlist
from grow.model.track.Fields import Fields as TrackFields
from grow.model.track.Track import Track

from .Fields import Fields
from .TrackPlaylistRelManager import TrackPlaylistRelManager

User = get_user_model()


class TrackPlaylistRel(PrivateStandardResource):
    playlist: Playlist = PrivateForeignKey(  # type: ignore
        Playlist, on_delete=models.CASCADE, related_name=PlayListFields.TRACK_PLAYLIST_RELS_INTERNAL
    )
    track: Track = PrivateForeignKey(  # type: ignore
        Track, on_delete=models.CASCADE, related_name=TrackFields.TRACK_PLAYLIST_RELS
    )
    position = models.PositiveIntegerField(null=True, blank=True)

    objects: TrackPlaylistRelManager = TrackPlaylistRelManager()

    class Meta:
        db_table = "grow_track_playlist_rel"
        verbose_name = "Track Playlist Relation"
        verbose_name_plural = "Track Playlist Relations"
        indexes = [
            models.Index(fields=[Fields.USER, Fields.PLAYLIST]),
            models.Index(fields=[Fields.USER, Fields.TRACK_INTERNAL]),
        ]

    def __str__(self):
        return (
            f'Playlist "{self.playlist.name}" | Lib track title "{self.track.title}" | '
            f"Position {self.position} User {self.user}"
        )

    def _perform_save(self, adding: bool, ctx: SaveContext) -> None:
        if adding:
            track_playlist_rels = TrackPlaylistRel.objects.filter(user=self.user, playlist=self.playlist)
            track_playlist_rels.update(
                position=Case(
                    When(**{Fields.POSITION + "__isnull": False}, then=F(Fields.POSITION) + 1), default=Value(None)
                )
            )
            self.position = 1
        super()._perform_save(adding, ctx)
