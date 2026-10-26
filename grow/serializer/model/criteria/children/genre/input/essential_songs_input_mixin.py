from rest_framework import serializers
from rest_framework.relations import PrimaryKeyRelatedField

from grow.model.song.Song import Song


class EssentialSongsInputMixin(serializers.Serializer):
    essential_songs = PrimaryKeyRelatedField(queryset=Song.objects.all(), many=True, required=False)
