from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer

from grow.model.artist.Artist import Artist
from grow.model.artist.Fields import Fields as ModelFields


class ArtistMinimumSerializer(AppInputSerializer, serializers.ModelSerializer):
    is_special_purpose = serializers.BooleanField(read_only=True)

    class Meta:
        model = Artist
        fields = [ModelFields.UUID, ModelFields.NAME_PUBLIC, ModelFields.IS_SPECIAL_PURPOSE]
