from rest_framework import serializers

from .simple import GenreSimpleSerializer


class GenreNameConflictGroupSerializer(serializers.Serializer):
    name = serializers.CharField()
    genres = GenreSimpleSerializer(many=True)
