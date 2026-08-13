from rest_framework import serializers

from grow.model.artist.Artist import Artist
from grow.serializer.model.album.minimum import AlbumMinimumSerializer
from grow.serializer.model.uploaded_track.output.simple.simple_without_artist import (
    UploadedTrackSimpleWithoutPlaylistAndArtistSerializer,
)

from .Fields import Fields


class ArtistDetailedSerializer(serializers.ModelSerializer):
    albums = AlbumMinimumSerializer(many=True)
    uploaded_tracks = UploadedTrackSimpleWithoutPlaylistAndArtistSerializer(
        source=Fields.UPLOADED_TRACKS_NOT_ARCHIVED_INTERNAL, many=True
    )
    uploaded_tracks_count = serializers.IntegerField(source=Fields.UPLOADED_TRACKS_NOT_ARCHIVED_COUNT_INTERNAL)
    uploaded_tracks_archived_count = serializers.IntegerField()

    class Meta:
        model = Artist
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.ALBUMS,
            Fields.UPLOADED_TRACKS_NOT_ARCHIVED_PUBLIC,
            Fields.UPLOADED_TRACKS_NOT_ARCHIVED_COUNT_PUBLIC,
            Fields.UPLOADED_TRACKS_ARCHIVED_COUNT_PUBLIC,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
