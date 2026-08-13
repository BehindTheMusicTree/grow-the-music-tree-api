from rest_framework import serializers

from grow.model.playlist.Playlist import Playlist
from grow.serializer.model.playlist.base.output.Fields import Fields as AvailableFields


class Fields:
    UUID = AvailableFields.UUID
    NAME = AvailableFields.NAME


class PlaylistMinimumSerializer(serializers.ModelSerializer):
    class Meta:
        model = Playlist
        fields = [Fields.UUID, Fields.NAME]
