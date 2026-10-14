from django.db.models import F, Q, QuerySet
from django_filters import CharFilter, ChoiceFilter, UUIDFilter
from the_music_tree_api_kit.filtering.filter.char.EmptiableCharFilter import EmptiableCharFilter
from the_music_tree_api_kit.filtering.filter.char.RelatedObjectCharFilter import RelatedObjectCharFilter
from the_music_tree_api_kit.filtering.set.private_unique_resource.PrivateUniqueResourceFilterSet import (
    PrivateUniqueResourceFilterSet,
)

from grow.model.album.Fields import Fields as AlbumFields
from grow.model.artist.Fields import Fields as ArtistFields
from grow.model.criteria.Criteria import Fields as CriteriaFields
from grow.model.criteria.lineage_rel.CriteriaLineageRel import CriteriaLineageRel
from grow.model.recording.Fields import Fields as ModelFields
from grow.model.recording.Recording import Recording

from .Fields import Fields

ORDERINGS = {"title": ModelFields.TITLE, "albumYear": f"{ModelFields.ALBUM}__{AlbumFields.YEAR}"}


class RecordingFilterSet(PrivateUniqueResourceFilterSet):
    title = CharFilter(field_name=ModelFields.TITLE, lookup_expr="icontains")
    artists_name = RelatedObjectCharFilter(
        primary_field=ArtistFields.NAME_INTERNAL,
        field_name=ModelFields.ARTISTS,
        field_name_public=Fields.ARTISTS_NAME,
        lookup_expr="icontains",
    )
    album_name = RelatedObjectCharFilter(
        primary_field=AlbumFields.NAME_INTERNAL,
        field_name=ModelFields.ALBUM,
        field_name_public=Fields.ALBUM_NAME,
        lookup_expr="icontains",
    )
    genre_name = RelatedObjectCharFilter(
        primary_field=CriteriaFields.NAME_INTERNAL,
        field_name=ModelFields.GENRE,
        field_name_public=Fields.GENRE_NAME,
        lookup_expr="icontains",
    )
    genre = UUIDFilter(method="filter_genre")
    artist = UUIDFilter(field_name=ModelFields.ARTISTS)
    ordering = ChoiceFilter(
        choices=[(f"{sign}{key}", f"{sign}{key}") for key in ORDERINGS for sign in ("", "-")], method="filter_ordering"
    )
    language = EmptiableCharFilter(
        field_name_public=ModelFields.LANGUAGE, field_name=ModelFields.LANGUAGE, lookup_expr="icontains"
    )

    class Meta:
        model = Recording
        fields = [Fields.TITLE, Fields.LANGUAGE, *PrivateUniqueResourceFilterSet.get_date_fields()]

    def filter_genre(self, queryset: QuerySet[Recording], name: str, value) -> QuerySet[Recording]:
        """The genre's recordings and its primary descendants', the same subtree its playlists cover."""
        descendants = CriteriaLineageRel.objects.filter(ascendant=value).values("descendant")
        return queryset.filter(Q(genre=value) | Q(genre__in=descendants))

    def filter_ordering(self, queryset: QuerySet[Recording], name: str, value: str) -> QuerySet[Recording]:
        field = F(ORDERINGS[value.lstrip("-")])
        descending = value.startswith("-")
        # Album-less recordings last either way; pk tie-breaker so OFFSET pages over tied rows neither repeat nor skip.
        return queryset.order_by(
            field.desc(nulls_last=True) if descending else field.asc(nulls_last=True),
            "-pk" if descending else "pk",
        )
