from django.db.models import Q
from django_filters import ChoiceFilter
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName

from grow.filtering.filter.char.CriteriaNameFilter import CriteriaNameFilter
from grow.filtering.filter.foreign_key.ForeignKeyFilter import ForeignKeyFilter
from grow.filtering.set.private_unique_resource.PrivateUniqueResourceFilterSet import PrivateUniqueResourceFilterSet
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.children.criteria.Fields import Fields as ModelFields

from .Fields import Fields


class CriteriaPlaylistFilterSet(PrivateUniqueResourceFilterSet):
    name = CriteriaNameFilter(
        field_name=f"{ModelFields.CRITERIA}__{ModelFields.NAME}",
        field_name_public=Fields.NAME_PUBLIC,
        lookup_expr="icontains",
    )
    parent = ForeignKeyFilter()
    tree_name = ChoiceFilter(choices=CriteriaTreeName.choices, method="filter_tree_name")

    class Meta:
        model = CriteriaPlaylist
        fields = [
            Fields.NAME_PUBLIC,
            Fields.PARENT,
            Fields.TREE_NAME,
            *PrivateUniqueResourceFilterSet.get_date_fields(),
        ]

    def filter_tree_name(self, queryset, name, value):
        tree_name_filter = Q(**{f"{ModelFields.CRITERIA}__{name}": value})
        if value == CriteriaTreeName.CANONICAL:
            # Genreless/Tagless playlists have no criteria and belong to the canonical tree.
            tree_name_filter |= Q(**{f"{ModelFields.CRITERIA}__isnull": True})
        return queryset.filter(tree_name_filter)
