from rest_framework import serializers
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField

from grow.model.playlist.children.manual.ManualPlaylist import ManualPlaylist
from grow.serializer.model.track.output.simple.simple_without_album_and_genre import (
    TrackWithoutAlbumPlaylistGenreSerializer,
)

from .Fields import Fields


class ManualPlaylistDetailedSerializer(serializers.ModelSerializer):
    name = AppCharField()
    tracks = TrackWithoutAlbumPlaylistGenreSerializer(many=True)
    tracks_count = serializers.IntegerField()

    class Meta:
        model = ManualPlaylist
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.TRACKS_PUBLIC,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.PLAY_COUNT,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
