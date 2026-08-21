from typing import Any

from rest_framework import serializers
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField

from grow.model.play.Play import Play
from grow.model.playlist.Playlist import Playlist
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from grow.serializer.model.playlist.base.output.detailed import PlaylistDetailedSerializer
from grow.serializer.model.youtube_track.output.detailed import YoutubeTrackDetailedSerializer

from .Fields import Fields


class PlayDetailedSerializer(serializers.ModelSerializer):
    content_type = AppCharField(source=f"{Fields.CONTENT_TYPE}.model")
    content = serializers.SerializerMethodField()

    class Meta:
        model = Play
        fields = [Fields.UUID, Fields.CONTENT_TYPE, Fields.CONTENT, Fields.CREATED_ON]

    def get_content(self, obj: Play) -> list | Any | dict:
        if isinstance(obj.content, Playlist):
            return PlaylistDetailedSerializer(obj.content).data
        if isinstance(obj.content, YoutubeTrack):
            return YoutubeTrackDetailedSerializer(obj.content).data
        raise NotImplementedError(f"No detailed serializer for track type {type(obj.content).__name__}")
