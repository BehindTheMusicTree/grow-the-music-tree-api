from rest_framework import serializers

from grow.model.album.Album import Album
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer

from .Fields import Fields


class AlbumSimpleSerializer(serializers.ModelSerializer):
    album_artists = ArtistMinimumSerializer(many=True)
    tracks_count = serializers.IntegerField(source=Fields.TRACKS_NOT_ARCHIVED_COUNT_INTERNAL)

    class Meta:
        model = Album
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.YEAR,
            Fields.ALBUM_ARTISTS,
            Fields.TRACKS_NOT_ARCHIVED_COUNT_PUBLIC,
            Fields.CREATED_ON,
        ]
