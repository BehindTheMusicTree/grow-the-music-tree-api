from rest_framework import serializers

from grow.model.artist.Artist import Artist
from grow.serializer.model.album.minimum import AlbumMinimumSerializer
from grow.serializer.model.track.output.simple.simple_without_artist import (
    TrackSimpleWithoutPlaylistAndArtistSerializer,
)

from .Fields import Fields


class ArtistDetailedSerializer(serializers.ModelSerializer):
    albums = AlbumMinimumSerializer(many=True)
    tracks = TrackSimpleWithoutPlaylistAndArtistSerializer(source=Fields.TRACKS_NOT_ARCHIVED_INTERNAL, many=True)
    tracks_count = serializers.IntegerField(source=Fields.TRACKS_NOT_ARCHIVED_COUNT_INTERNAL)
    tracks_archived_count = serializers.IntegerField()

    class Meta:
        model = Artist
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.ALBUMS,
            Fields.TRACKS_NOT_ARCHIVED_PUBLIC,
            Fields.TRACKS_NOT_ARCHIVED_COUNT_PUBLIC,
            Fields.TRACKS_ARCHIVED_COUNT_PUBLIC,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
