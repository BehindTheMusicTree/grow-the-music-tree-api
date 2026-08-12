from rest_framework import serializers

from grow.model.album.Album import Album
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.uploaded_track.output.simple.simple_without_album_with_track_number import (
    UploadedTrackSimpleWithoutAlbumWithPositionInAlbumSerializer,
)

from .Fields import Fields


class AlbumDetailedSerializer(serializers.ModelSerializer):
    uploaded_tracks_sorted = UploadedTrackSimpleWithoutAlbumWithPositionInAlbumSerializer(
        source=Fields.UPLOADED_TRACKS_NOT_ARCHIVED_SORTED_INTERNAL, many=True
    )
    uploaded_tracks_count = serializers.IntegerField(source=Fields.UPLOADED_TRACKS_NOT_ARCHIVED_COUNT_INTERNAL)
    uploaded_tracks_archived_count = serializers.IntegerField()
    album_artists = ArtistMinimumSerializer(many=True)

    class Meta:
        model = Album
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.YEAR,
            Fields.ALBUM_ARTISTS,
            Fields.UPLOADED_TRACKS_NOT_ARCHIVED_SORTED_PUBLIC,
            Fields.UPLOADED_TRACKS_NOT_ARCHIVED_COUNT_PUBLIC,
            Fields.UPLOADED_TRACKS_ARCHIVED_COUNT_PUBLIC,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
