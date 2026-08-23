from rest_framework import serializers

from grow.model.album.Album import Album
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.track.output.simple.simple_without_album_with_track_number import (
    TrackSimpleWithoutAlbumWithPositionInAlbumSerializer,
)

from .Fields import Fields


class AlbumDetailedSerializer(serializers.ModelSerializer):
    tracks_sorted = TrackSimpleWithoutAlbumWithPositionInAlbumSerializer(
        source=Fields.TRACKS_NOT_ARCHIVED_SORTED_INTERNAL, many=True
    )
    tracks_count = serializers.IntegerField(source=Fields.TRACKS_NOT_ARCHIVED_COUNT_INTERNAL)
    tracks_archived_count = serializers.IntegerField()
    album_artists = ArtistMinimumSerializer(many=True)

    class Meta:
        model = Album
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.YEAR,
            Fields.ALBUM_ARTISTS,
            Fields.TRACKS_NOT_ARCHIVED_SORTED_PUBLIC,
            Fields.TRACKS_NOT_ARCHIVED_COUNT_PUBLIC,
            Fields.TRACKS_ARCHIVED_COUNT_PUBLIC,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
