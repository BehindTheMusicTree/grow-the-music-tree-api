from the_music_tree_api_kit.filtering.filter.StrictBooleanFilter import StrictBooleanFilter

from grow.filtering.set.criteria.CriteriaFilterSet import CriteriaFilterSet


class GenreFilterSet(CriteriaFilterSet):
    has_name_conflict = StrictBooleanFilter(field_name="has_name_conflict")
    is_unaccepted_root = StrictBooleanFilter(field_name="is_unaccepted_root")

    class Meta(CriteriaFilterSet.Meta):
        fields = [*CriteriaFilterSet.Meta.fields, "has_name_conflict", "is_unaccepted_root"]
