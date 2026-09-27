from rest_framework import serializers
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_genre_kit.criteria.track_playlist_rel.tracks_count_annotation import tracks_count_annotation

from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer
from grow.serializer.model.playlist.base.output.Fields import Fields as PlaylistOutputFields
from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer
from grow.serializer.model.track_playlist_rel.output.without_playlist import TrackPlaylistRelWithoutPlaylist

from .Fields import Fields


class CriteriaPlaylistDetailedSerializer(EagerLoadingMixin, serializers.ModelSerializer):
    track_playlist_relations = TrackPlaylistRelWithoutPlaylist(source=Fields.TRACK_PLAYLIST_RELS_INTERNAL, many=True)
    tracks_count = serializers.IntegerField(source=PlaylistOutputFields.TRACKS_COUNT_ANNOTATED)
    criteria = CriteriaMinimumSerializer()
    root = CriteriaPlaylistMinimumSerializer()  # type: ignore
    parent = CriteriaPlaylistMinimumSerializer()

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        for nested in ("", f"{Fields.PARENT}__", f"{Fields.ROOT}__"):
            queryset = CriteriaPlaylistMinimumSerializer.setup_queryset(queryset, prefix=f"{prefix}{nested}")
        queryset = queryset.annotate(**{PlaylistOutputFields.TRACKS_COUNT_ANNOTATED: tracks_count_annotation()})
        return TrackPlaylistRelWithoutPlaylist.prefetch(queryset, f"{prefix}{Fields.TRACK_PLAYLIST_RELS_INTERNAL}")

    class Meta:
        model = CriteriaPlaylist
        fields = [
            Fields.UUID,
            Fields.NAME,
            Fields.TRACK_PLAYLIST_RELS_PUBLIC,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.CRITERIA,
            Fields.PARENT,
            Fields.ROOT,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
