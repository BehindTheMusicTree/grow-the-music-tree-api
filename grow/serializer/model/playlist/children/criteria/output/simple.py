from django.core.exceptions import ImproperlyConfigured
from rest_framework import serializers
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_genre_kit.criteria.track_playlist_rel.tracks_count_annotation import tracks_count_annotation

from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.serializer.model.criteria.output.simple import CriteriaSimpleSerializer
from grow.serializer.model.playlist.base.output.Fields import Fields as PlaylistOutputFields
from grow.serializer.model.playlist.children.criteria.output.Fields import Fields as AvailableFields
from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer


class Fields:
    UUID = AvailableFields.UUID
    NAME = AvailableFields.NAME
    TRACKS_COUNT_INTERNAL = AvailableFields.TRACKS_COUNT_INTERNAL
    TRACKS_COUNT_PUBLIC = AvailableFields.TRACKS_COUNT_PUBLIC
    CRITERIA = AvailableFields.CRITERIA
    PARENT = AvailableFields.PARENT
    ROOT = AvailableFields.ROOT
    CREATED_ON = AvailableFields.CREATED_ON
    UPDATED_ON = AvailableFields.UPDATED_ON


class CriteriaPlaylistSimpleSerializer(EagerLoadingMixin, serializers.ModelSerializer):
    criteria = CriteriaSimpleSerializer()
    parent = CriteriaPlaylistMinimumSerializer()
    root = CriteriaPlaylistMinimumSerializer()  # type: ignore
    tracks_count = serializers.IntegerField(source=PlaylistOutputFields.TRACKS_COUNT_ANNOTATED)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        queryset = CriteriaPlaylistMinimumSerializer.setup_queryset(queryset, prefix)
        queryset = CriteriaSimpleSerializer.setup_queryset(queryset, prefix=f"{prefix}{Fields.CRITERIA}__")
        for nested in (Fields.PARENT, Fields.ROOT):
            queryset = CriteriaPlaylistMinimumSerializer.setup_queryset(queryset, prefix=f"{prefix}{nested}__")
        return queryset.annotate(**{PlaylistOutputFields.TRACKS_COUNT_ANNOTATED: tracks_count_annotation()})

    def to_representation(self, instance):
        if not isinstance(instance, CriteriaPlaylist):
            raise ImproperlyConfigured("Invalid instance type")
        return super().to_representation(instance)

    class Meta:
        model = CriteriaPlaylist
        fields = [
            Fields.UUID,
            Fields.NAME,
            Fields.CRITERIA,
            Fields.PARENT,
            Fields.ROOT,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
