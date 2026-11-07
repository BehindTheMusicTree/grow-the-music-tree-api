from rest_framework import serializers
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.genre_music.summary import GenrePlaylistSummaryMixin, playlist_tracks_count_annotation
from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer

from .Fields import Fields


class PlaylistDetailedSerializer(GenrePlaylistSummaryMixin, EagerLoadingMixin, serializers.ModelSerializer):
    tracks_count = serializers.IntegerField(source=Fields.TRACKS_COUNT_ANNOTATED)
    type = AppCharField(source=Fields.TYPE_LABEL_INTERNAL)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        return PlaylistMinimumSerializer.setup_queryset(queryset, prefix).annotate(
            **{Fields.TRACKS_COUNT_ANNOTATED: playlist_tracks_count_annotation()}
        )

    class Meta:
        model = Playlist
        fields = [
            Fields.UUID,
            Fields.NAME,
            Fields.TYPE_LABEL_PUBLIC,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.PLAY_COUNT,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
