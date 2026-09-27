from rest_framework import serializers

from grow.model.artist.Artist import Artist
from grow.serializer.model.album.minimum import AlbumMinimumSerializer
from grow.serializer.model.track.output.simple.simple_without_artist import (
    TrackSimpleWithoutPlaylistAndArtistSerializer,
)

from .Fields import Fields


class ArtistDetailedSerializer(serializers.ModelSerializer):
    albums = AlbumMinimumSerializer(many=True)
    tracks = TrackSimpleWithoutPlaylistAndArtistSerializer(many=True)
    tracks_count = serializers.IntegerField()

    class Meta:
        model = Artist
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.ALBUMS,
            Fields.TRACKS_PUBLIC,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
