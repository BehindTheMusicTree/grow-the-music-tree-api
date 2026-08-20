from rest_framework import serializers
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField

from grow.model.playlist.children.manual.ManualPlaylist import ManualPlaylist

from .Fields import Fields


class ManualPlaylistSimpleSerializer(serializers.ModelSerializer):
    name = AppCharField()
    tracks_count = serializers.IntegerField(source=Fields.TRACKS_NOT_ARCHIVED_COUNT_INTERNAL)

    class Meta:
        model = ManualPlaylist
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.TRACKS_NOT_ARCHIVED_COUNT_PUBLIC,
            Fields.CREATED_ON,
        ]
