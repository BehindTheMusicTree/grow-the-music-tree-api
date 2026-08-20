from django.conf import settings
from django.db import models
from the_music_tree_api_kit.field.AppCharField import AppCharField
from the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField import PrivateOneToOneField

from grow.model.track.Fields import Fields as TrackFields
from grow.model.track.Track import Track
from grow.model.track.TrackManager import TrackManager


class YoutubeTrack(Track):
    track = PrivateOneToOneField(
        Track, on_delete=models.CASCADE, parent_link=True, related_name=TrackFields.YOUTUBE_TRACK_RELATED_NAME
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
