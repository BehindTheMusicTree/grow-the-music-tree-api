from grow.filtering.filter.char.NonEmptiableCharFilter import NonEmptiableCharFilter
from grow.filtering.set.private_unique_resource.PrivateUniqueResourceFilterSet import PrivateUniqueResourceFilterSet
from grow.model.playlist.children.manual.ManualPlaylist import ManualPlaylist

from .Fields import Fields


class ManualPlaylistFilterSet(PrivateUniqueResourceFilterSet):
    name = NonEmptiableCharFilter(lookup_expr="icontains")

    class Meta:
        model = ManualPlaylist
        fields = [Fields.NAME_PUBLIC, *PrivateUniqueResourceFilterSet.get_date_fields()]
