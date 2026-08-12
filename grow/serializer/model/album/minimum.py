from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer

from grow.model.album.Album import Album
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer

from .Fields import Fields


class AlbumMinimumSerializer(AppInputSerializer, serializers.ModelSerializer):
    album_artists = ArtistMinimumSerializer(many=True)

    class Meta:
        model = Album
        fields = [Fields.UUID, Fields.NAME_PUBLIC, Fields.ALBUM_ARTISTS]
