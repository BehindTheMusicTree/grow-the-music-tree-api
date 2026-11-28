from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from grow.openapi.documents import component_ref, object_schema

PROVENANCE_SCHEMA = object_schema(
    {
        "decisionId": {"type": "string", "pattern": r"\S"},
        "source": {"type": "string", "pattern": r"\S"},
        "rationale": {"type": "string", "pattern": r"\S"},
    }
)
EVIDENCE_SCHEMA = object_schema(
    {
        **PROVENANCE_SCHEMA["properties"],
        "decisionId": {**PROVENANCE_SCHEMA["properties"]["decisionId"], "maxLength": 255},
    }
)
RETIREMENTS_SCHEMA = {
    "type": "object",
    "additionalProperties": object_schema({"target": {"type": ["string", "null"]}, "provenance": PROVENANCE_SCHEMA}),
}
ASSIGNMENTS_SCHEMA = {
    "type": "object",
    "maxProperties": 1,
    "additionalProperties": {"type": "array", "minItems": 1, "items": EVIDENCE_SCHEMA},
}


@extend_schema_field(component_ref("GenreGraph"))
class GenreGraphField(serializers.DictField):
    pass


@extend_schema_field(RETIREMENTS_SCHEMA)
class RetirementsField(serializers.DictField):
    pass


@extend_schema_field(ASSIGNMENTS_SCHEMA)
class AttributionsField(serializers.DictField):
    pass


@extend_schema_field(PROVENANCE_SCHEMA)
class GraphProvenanceField(serializers.DictField):
    pass


class GraphRevisionSerializer(serializers.Serializer):
    revision = serializers.UUIDField(allow_null=True)


class GraphTokensSerializer(serializers.Serializer):
    revision = serializers.UUIDField()
    membership_revision = serializers.UUIDField()


class GraphAssignmentTokensSerializer(GraphTokensSerializer):
    assignment_revision = serializers.UUIDField(allow_null=True)


class ReferenceGraphSerializer(GraphTokensSerializer):
    graph = GenreGraphField(help_text="The reference graph payload, verbatim.")
    mapping = serializers.DictField(child=serializers.UUIDField(), help_text="Node identity to genre uuid.")


class SongAttributionsSerializer(GraphAssignmentTokensSerializer):
    attributions = AttributionsField(help_text="Direct attributions of the song, by node identity.")
    effective_attributions = serializers.ListField(child=serializers.CharField())
    needs_refinement = serializers.BooleanField()
