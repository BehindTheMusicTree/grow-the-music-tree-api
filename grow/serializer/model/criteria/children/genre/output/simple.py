from rest_framework import serializers

from grow.serializer.model.criteria.output.simple import CriteriaSimpleSerializer


class GenreSimpleSerializer(CriteriaSimpleSerializer):  # type: ignore[valid-type,misc]
    has_name_conflict = serializers.BooleanField(read_only=True)

    class Meta(CriteriaSimpleSerializer.Meta):  # type: ignore[name-defined]
        fields = [*CriteriaSimpleSerializer.Meta.fields, "has_name_conflict"]  # type: ignore[attr-defined]
