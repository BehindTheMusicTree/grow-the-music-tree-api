from rest_framework import serializers

from .simple import GenreSimpleSerializer


class GenreNameConflictMemberSerializer(GenreSimpleSerializer):
    wikidata_id = serializers.CharField(read_only=True)

    class Meta(GenreSimpleSerializer.Meta):
        fields = [*GenreSimpleSerializer.Meta.fields, "wikidata_id"]


class GenreNameConflictGroupSerializer(serializers.Serializer):
    name = serializers.CharField()
    genres = GenreNameConflictMemberSerializer(many=True)
