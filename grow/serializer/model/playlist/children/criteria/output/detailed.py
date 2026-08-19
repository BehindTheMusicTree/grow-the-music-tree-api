from rest_framework import serializers

from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer
from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer
from grow.serializer.model.track_playlist_rel.output.without_playlist import TrackPlaylistRelWithoutPlaylist

from .Fields import Fields


class CriteriaPlaylistDetailedSerializer(serializers.ModelSerializer):
    track_playlist_relations = TrackPlaylistRelWithoutPlaylist(source=Fields.TRACK_PLAYLIST_RELS_INTERNAL, many=True)
    tracks_count = serializers.IntegerField(source=Fields.TRACKS_NOT_ARCHIVED_COUNT_INTERNAL)
    tracks_archived_count = serializers.IntegerField(source=Fields.TRACKS_ARCHIVED_COUNT_INTERNAL)
    criteria = CriteriaMinimumSerializer()
    root = CriteriaPlaylistMinimumSerializer()  # type: ignore
    parent = CriteriaPlaylistMinimumSerializer()

    class Meta:
        model = CriteriaPlaylist
        fields = [
            Fields.UUID,
            Fields.NAME,
            Fields.TRACK_PLAYLIST_RELS_PUBLIC,
            Fields.TRACKS_NOT_ARCHIVED_COUNT_PUBLIC,
            Fields.TRACKS_ARCHIVED_COUNT_PUBLIC,
            Fields.CRITERIA,
            Fields.PARENT,
            Fields.ROOT,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
