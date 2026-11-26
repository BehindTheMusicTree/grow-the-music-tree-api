from rest_framework import serializers

from grow.serializer.schema.common import ImportRunCreateRequestSerializer


class SongImportExpectedPartsSerializer(serializers.Serializer):
    songs = serializers.IntegerField(min_value=0)
    assignments = serializers.IntegerField(min_value=0)
    deletions = serializers.IntegerField(min_value=0, max_value=1, required=False, help_text="Delta runs only.")


class SongImportRunCreateRequestSerializer(ImportRunCreateRequestSerializer):
    graph_revision = serializers.UUIDField(help_text="Reviewed reference graph revision.")
    membership_revision = serializers.UUIDField(help_text="Reviewed genre membership revision.")
    expected_parts = SongImportExpectedPartsSerializer(
        help_text=(
            "Exactly `songs` and `assignments` for a `full` run (with `songs` at least 1), plus `deletions` for a"
            " `delta` run; any other key set is rejected."
        )
    )


class SongPreviousGenreSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    genre = serializers.UUIDField(allow_null=True)
    undoable = serializers.BooleanField(help_text="Always false. Use the response's undo token to restore the edit.")


class SongAssignGenreResultSerializer(serializers.Serializer):
    previous = SongPreviousGenreSerializer(many=True)
    undo_token = serializers.UUIDField()
