from functools import reduce
from operator import or_

from django.db.models.query import QuerySet
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks

from grow.filtering.filter.char.NonEmptiableCharFilter import NonEmptiableCharFilter
from grow.filtering.filter.char.OptionalEnumCharFilter import OptionalEnumCharFilter
from grow.filtering.set.private_unique_resource.PrivateUniqueResourceFilterSet import PrivateUniqueResourceFilterSet
from grow.model.playlist.children.criteria.CriterialessPlaylistNames import CriterialessPlaylistNames
from grow.model.playlist.Fields import Fields as ModelFields
from grow.model.playlist.Playlist import Playlist
from grow.model.playlist.PlaylistTypesLabel import PlaylistTypesLabel

from .Fields import Fields


class PlaylistFilterSet(PrivateUniqueResourceFilterSet):
    name = NonEmptiableCharFilter(method="filter_by_name_and_type")
    type = OptionalEnumCharFilter(enum_class=PlaylistTypesLabel, method="filter_by_name_and_type")

    class Meta:
        model = Playlist
        fields = [Fields.NAME, Fields.TYPE_LABEL_PUBLIC, *PrivateUniqueResourceFilterSet.get_date_fields()]

    def filter_by_name_and_type(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        name_value = self.data.get(Fields.NAME)
        type_label = self.data.get(Fields.TYPE_LABEL_PUBLIC)

        base_queryset = queryset.order_by(ModelFields.CREATED_ON)

        result_querysets = []

        if type_label is None or type_label.lower() == PlaylistTypesLabel.MANUAL.lower():
            manual_qs = base_queryset.filter(
                manual_playlist__isnull=False,
                manual_playlist__name__icontains=name_value if name == Fields.NAME else "",
            )
            result_querysets.append(manual_qs)

        if type_label is None or type_label.lower() in [
            PlaylistTypesLabel.GENRE.lower(),
            PlaylistTypesLabel.TAG.lower(),
        ]:
            criteria_qs = base_queryset.filter(
                criteria_playlist__isnull=False,
                criteria_playlist__type__label__icontains=type_label.upper() if type_label else "",
                criteria_playlist__criteria__name__icontains=name_value if name == Fields.NAME else "",
            )
            result_querysets.append(criteria_qs)

        if (not name_value or name_value.lower() in CriterialessPlaylistNames.GENRE.lower()) and type_label in [
            None,
            PlaylistTypesLabel.GENRE,
        ]:
            genreless_qs = base_queryset.filter(
                criteria_playlist__isnull=False,
                criteria_playlist__criteria__isnull=True,
                criteria_playlist__type_id=CriteriaTypePks.GENRE,
            )
            result_querysets.append(genreless_qs)

        if (not name_value or name_value.lower() in CriterialessPlaylistNames.TAG.lower()) and type_label in [
            None,
            PlaylistTypesLabel.TAG,
        ]:
            tagless_qs = base_queryset.filter(
                criteria_playlist__isnull=False,
                criteria_playlist__criteria__isnull=True,
                criteria_playlist__type_id=CriteriaTypePks.TAG,
            )
            result_querysets.append(tagless_qs)

        if not result_querysets:
            return Playlist.objects.none()

        return reduce(or_, result_querysets)
