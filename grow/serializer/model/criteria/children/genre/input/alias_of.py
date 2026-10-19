from rest_framework import serializers


class GenreAliasOfSerializer(serializers.Serializer):
    target = serializers.UUIDField()
