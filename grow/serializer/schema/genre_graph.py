from rest_framework import serializers


class GraphRevisionSerializer(serializers.Serializer):
    revision = serializers.UUIDField(allow_null=True)


class GraphTokensSerializer(serializers.Serializer):
    revision = serializers.UUIDField()
    membership_revision = serializers.UUIDField()


class GraphAssignmentTokensSerializer(GraphTokensSerializer):
    assignment_revision = serializers.UUIDField(allow_null=True)


class ReferenceGraphSerializer(GraphTokensSerializer):
    graph = serializers.DictField(help_text="The reference graph payload, verbatim.")
    mapping = serializers.DictField(child=serializers.UUIDField(), help_text="Node identity to genre uuid.")


class SongAttributionsSerializer(GraphAssignmentTokensSerializer):
    attributions = serializers.DictField(help_text="Direct attributions of the song, by node identity.")
    effective_attributions = serializers.ListField(child=serializers.CharField())
    needs_refinement = serializers.BooleanField()
