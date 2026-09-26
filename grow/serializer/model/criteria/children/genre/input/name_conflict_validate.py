from django.conf import settings
from rest_framework import serializers
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField


class GenreNameConflictNameSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = AppCharField(max_length=settings.CRITERIA_NAME_LEN_MAX)


class GenreNameConflictValidateSerializer(serializers.Serializer):
    genres = GenreNameConflictNameSerializer(many=True, allow_empty=False)

    def validate_genres(self, genres):
        if len({genre["uuid"] for genre in genres}) != len(genres):
            raise serializers.ValidationError("Each genre can only appear once")
        return genres
