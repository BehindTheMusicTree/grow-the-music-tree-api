from typing import Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from the_music_tree_api_kit.serializer.field.foreign_key.PrivateUuidField import PrivateUuidField

from grow.model.ContentObjectFields import ContentObjectFields
from grow.model.playlist.Playlist import Playlist
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack


class PrivateContentUuidField(PrivateUuidField):
    """
    Special case of PrivateUuidField that allows references to either Playlists or Tracks.
    Used when a field can accept either type of content.

    This field is used when:
    1. The UUID could point to either a Playlist or Track
    2. Both model types are treated as valid options
    3. The referenced object must belong to the current user

    Example:
        class PlaySerializer(serializers.ModelSerializer):
            content = PrivateContentUuidField()  # Can reference either model type
    """

    default_error_messages = {
        "invalid": "Invalid UUID format.",
        "does_not_exist": "Object with this UUID does not exist.",
        "no_request": "Request context is required.",
    }

    def __init__(self, **kwargs):
        # Set read_only=False since we handle writes
        kwargs["read_only"] = False
        super().__init__(**kwargs)
        # Initialize content type cache as None
        self._playlist_ct = None
        self._track_ct = None

    def _get_playlist_ct(self):
        if self._playlist_ct is None:
            self._playlist_ct = ContentType.objects.get_for_model(Playlist)
        return self._playlist_ct

    def _get_track_ct(self):
        if self._track_ct is None:
            self._track_ct = ContentType.objects.get_for_model(YoutubeTrack)
        return self._track_ct

    def get_queryset(self):
        user = self.get_request_user()
        return Playlist.objects.filter(user=user) | YoutubeTrack.objects.filter(user=user)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if data is None:
            return {ContentObjectFields.CONTENT_TYPE: None, ContentObjectFields.CONTENT: None}

        try:
            uuid = UUID(str(data))
        except ValueError, AttributeError, TypeError:
            self.fail("invalid")
            return {}  # Never reached due to fail()

        user = self.get_request_user()

        # Check both models for the UUID, ensuring user ownership and get the actual object
        playlist = Playlist.objects.filter(user=user, uuid=uuid).first()
        if playlist:
            return {ContentObjectFields.CONTENT_TYPE: self._get_playlist_ct(), ContentObjectFields.CONTENT: playlist}

        track = YoutubeTrack.objects.filter(user=user, uuid=uuid).first()
        if track:
            return {
                ContentObjectFields.CONTENT_TYPE: self._get_track_ct(),
                ContentObjectFields.CONTENT: track,
            }
        self.fail("does_not_exist")

        return {}  # Never reached due to fail()
