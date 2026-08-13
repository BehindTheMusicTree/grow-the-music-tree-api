from rest_framework import serializers

from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer
from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer
from grow.serializer.model.uploaded_track_playlist_rel.output.without_playlist import (
    UploadedTrackPlaylistRelWithoutPlaylist,
)

from .Fields import Fields


class CriteriaPlaylistDetailedSerializer(serializers.ModelSerializer):
    uploaded_track_playlist_relations = UploadedTrackPlaylistRelWithoutPlaylist(
        source=Fields.UPLOADED_TRACK_PLAYLIST_RELS_INTERNAL, many=True
    )
    uploaded_tracks_count = serializers.IntegerField(source=Fields.UPLOADED_TRACKS_NOT_ARCHIVED_COUNT_INTERNAL)
    uploaded_tracks_archived_count = serializers.IntegerField()
    criteria = CriteriaMinimumSerializer()
    root = CriteriaPlaylistMinimumSerializer()  # type: ignore
    parent = CriteriaPlaylistMinimumSerializer()

    class Meta:
        model = CriteriaPlaylist
        fields = [
            Fields.UUID,
            Fields.NAME,
            Fields.UPLOADED_TRACK_PLAYLIST_RELS_PUBLIC,
            Fields.UPLOADED_TRACKS_NOT_ARCHIVED_COUNT_PUBLIC,
            Fields.UPLOADED_TRACKS_ARCHIVED_COUNT_PUBLIC,
            Fields.CRITERIA,
            Fields.PARENT,
            Fields.ROOT,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
