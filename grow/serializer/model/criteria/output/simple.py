from rest_framework import serializers
from the_music_tree_genre_kit.serializer.model.criteria.output.simple import build_criteria_simple_serializer

from grow.model.criteria.Criteria import Criteria

_KitCriteriaSimpleSerializer = build_criteria_simple_serializer(Criteria)


class CriteriaSimpleSerializer(_KitCriteriaSimpleSerializer):  # type: ignore[valid-type,misc]
    has_name_conflict = serializers.SerializerMethodField()

    class Meta(_KitCriteriaSimpleSerializer.Meta):  # type: ignore[name-defined]
        fields = [*_KitCriteriaSimpleSerializer.Meta.fields, "has_name_conflict"]  # type: ignore[attr-defined]

    def get_has_name_conflict(self, obj) -> bool:
        genre = getattr(obj, "genre", None)
        return bool(genre and genre.has_name_conflict)
