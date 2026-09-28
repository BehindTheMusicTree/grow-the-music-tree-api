from django_filters import BooleanFilter

from grow.filtering.set.criteria.CriteriaFilterSet import CriteriaFilterSet


class GenreFilterSet(CriteriaFilterSet):
    has_name_conflict = BooleanFilter(field_name="has_name_conflict")
    is_unaccepted_root = BooleanFilter(field_name="is_unaccepted_root")

    class Meta(CriteriaFilterSet.Meta):
        fields = [*CriteriaFilterSet.Meta.fields, "has_name_conflict", "is_unaccepted_root"]
