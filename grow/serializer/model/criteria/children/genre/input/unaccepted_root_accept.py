from rest_framework import serializers


class GenreUnacceptedRootUuidSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()


class GenreUnacceptedRootAcceptSerializer(serializers.Serializer):
    genres = GenreUnacceptedRootUuidSerializer(many=True, allow_empty=False)

    def validate_genres(self, genres):
        if len({genre["uuid"] for genre in genres}) != len(genres):
            raise serializers.ValidationError("Each genre can only appear once")
        return genres
