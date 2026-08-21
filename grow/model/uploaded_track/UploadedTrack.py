from django.db import models
from the_music_tree_api_kit.field.foreign_key.PrivateOneToOneField import PrivateOneToOneField
from the_music_tree_genre_kit.track.Track import Track as KitTrack

from grow.model.track.Fields import Fields as TrackFields
from grow.model.track.TrackConvenienceMixin import TrackConvenienceMixin
from grow.model.track.TrackManager import TrackManager


class UploadedTrack(TrackConvenienceMixin, KitTrack):
    track = PrivateOneToOneField(
        KitTrack, on_delete=models.CASCADE, parent_link=True, related_name=TrackFields.UPLOADED_TRACK_RELATED_NAME
    )

    objects: TrackManager[UploadedTrack] = TrackManager()

    class Meta:
        db_table = "grow_uploaded_track"
        verbose_name = "Uploaded Track"
        verbose_name_plural = "Uploaded Tracks"
