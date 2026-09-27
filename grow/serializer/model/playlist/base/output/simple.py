from rest_framework import serializers
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_genre_kit.criteria.track_playlist_rel.tracks_count_annotation import tracks_count_annotation
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.serializer.model.playlist.base.output.Fields import Fields as AvailableFields
from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer


class Fields:
    UUID = AvailableFields.UUID
    TRACKS_COUNT_INTERNAL = AvailableFields.TRACKS_COUNT_INTERNAL
    TRACKS_COUNT_PUBLIC = AvailableFields.TRACKS_COUNT_PUBLIC
    NAME = AvailableFields.NAME
    TYPE_LABEL_INTERNAL = AvailableFields.TYPE_LABEL_INTERNAL
    TYPE_LABEL_PUBLIC = AvailableFields.TYPE_LABEL_PUBLIC
    CREATED_ON = AvailableFields.CREATED_ON


class PlaylistSimpleSerializer(EagerLoadingMixin, serializers.ModelSerializer):
    type = AppCharField(source=Fields.TYPE_LABEL_INTERNAL)
    tracks_count = serializers.IntegerField(source=AvailableFields.TRACKS_COUNT_ANNOTATED)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        return PlaylistMinimumSerializer.setup_queryset(queryset, prefix).annotate(
            **{AvailableFields.TRACKS_COUNT_ANNOTATED: tracks_count_annotation()}
        )

    class Meta:
        model = Playlist
        fields = [
            Fields.UUID,
            Fields.NAME,
            Fields.TYPE_LABEL_PUBLIC,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.CREATED_ON,
        ]
