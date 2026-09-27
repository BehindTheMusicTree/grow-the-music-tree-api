from typing import Any

from django.contrib.contenttypes.prefetch import GenericPrefetch
from rest_framework import serializers
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.model.play.Play import Play
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer
from grow.serializer.model.youtube_track.output.minimum import YoutubeTrackMinimumSerializer

from .Fields import Fields


class PlayDetailedSerializer(EagerLoadingMixin, serializers.ModelSerializer):
    content_type = AppCharField(source=f"{Fields.CONTENT_TYPE}.model")
    content = serializers.SerializerMethodField()

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        playlists = PlaylistMinimumSerializer.setup_queryset(Playlist._default_manager.all())
        return queryset.select_related(f"{prefix}{Fields.CONTENT_TYPE}").prefetch_related(
            GenericPrefetch(f"{prefix}{Fields.CONTENT}", [playlists, YoutubeTrack._default_manager.all()])
        )

    class Meta:
        model = Play
        fields = [Fields.UUID, Fields.CONTENT_TYPE, Fields.CONTENT, Fields.CREATED_ON]

    def get_content(self, obj: Play) -> dict[str, Any]:
        if isinstance(obj.content, Playlist):
            return PlaylistMinimumSerializer(obj.content).data
        if isinstance(obj.content, YoutubeTrack):
            return YoutubeTrackMinimumSerializer(obj.content).data
        raise NotImplementedError(f"No minimum serializer for content type {type(obj.content).__name__}")
