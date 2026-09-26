from grow.filtering.filter.char.NonEmptiableCharFilter import NonEmptiableCharFilter
from grow.filtering.filter.foreign_key.DescendantAwareFilter import DescendantAwareFilter
from grow.filtering.set.private_unique_resource.PrivateUniqueResourceFilterSet import PrivateUniqueResourceFilterSet
from grow.model.criteria.Criteria import Criteria

from .Fields import Fields


class CriteriaFilterSet(PrivateUniqueResourceFilterSet):
    # field_name must be Fields.NAME_INTERNAL ("_name"): Criteria stores its name in the
    # `_name` model field (db_column="name"), so filtering must target the actual ORM
    # field, not the "name" property.
    name = NonEmptiableCharFilter(
        field_name=Fields.NAME_INTERNAL, field_name_public=Fields.NAME_PUBLIC, lookup_expr="icontains"
    )
    parent = DescendantAwareFilter(queryset=Criteria.objects.all())

    class Meta:
        model = Criteria
        fields = [Fields.NAME_PUBLIC, Fields.PARENT, *PrivateUniqueResourceFilterSet.get_date_fields()]
