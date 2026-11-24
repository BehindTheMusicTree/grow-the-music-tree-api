from rest_framework import serializers

from grow.serializer.schema.common import ImportRunCreateRequestSerializer


class SongImportExpectedPartsSerializer(serializers.Serializer):
    songs = serializers.IntegerField(min_value=0)
    assignments = serializers.IntegerField(min_value=0)
    deletions = serializers.IntegerField(min_value=0, max_value=1, required=False, help_text="Delta runs only.")


class SongImportRunCreateRequestSerializer(ImportRunCreateRequestSerializer):
    graph_revision = serializers.UUIDField(help_text="Reviewed reference graph revision.")
    membership_revision = serializers.UUIDField(help_text="Reviewed genre membership revision.")
    expected_parts = SongImportExpectedPartsSerializer()


class SongPreviousGenreSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    genre = serializers.UUIDField(allow_null=True)


class SongAssignGenreResultSerializer(serializers.Serializer):
    previous = SongPreviousGenreSerializer(many=True)
    undo_token = serializers.UUIDField()
