from rest_framework import serializers
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField

from grow.model.playlist.children.manual.ManualPlaylist import ManualPlaylist
from grow.serializer.model.uploaded_track.output.simple.simple_without_album_and_genre import (
    UploadedTrackWithoutAlbumPlaylistGenreSerializer,
)

from .Fields import Fields


class ManualPlaylistDetailedSerializer(serializers.ModelSerializer):
    name = AppCharField()
    uploaded_tracks = UploadedTrackWithoutAlbumPlaylistGenreSerializer(
        source=Fields.UPLOADED_TRACKS_NOT_ARCHIVED_INTERNAL, many=True
    )
    uploaded_tracks_count = serializers.IntegerField(source=Fields.UPLOADED_TRACKS_NOT_ARCHIVED_COUNT_INTERNAL)

    class Meta:
        model = ManualPlaylist
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.UPLOADED_TRACKS_NOT_ARCHIVED_PUBLIC,
            Fields.UPLOADED_TRACKS_NOT_ARCHIVED_COUNT_PUBLIC,
            Fields.PLAY_COUNT,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
