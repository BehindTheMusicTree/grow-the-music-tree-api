from rest_framework import serializers

from grow.model.song.Song import Song

from .SongOutputFieldKey import SongOutputFieldKey


class SongMinimumSerializer(serializers.ModelSerializer):
    class Meta:
        model = Song
        fields = [SongOutputFieldKey.UUID.value, SongOutputFieldKey.TITLE.value]
