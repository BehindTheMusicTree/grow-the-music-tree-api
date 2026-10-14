from django.db.models import Case, F, IntegerField, Q, QuerySet, When
from django.db.models.functions import Cast, Coalesce
from django_filters import BooleanFilter, CharFilter, ChoiceFilter, UUIDFilter
from rest_framework.exceptions import NotFound
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
from grow.view.pagination.OptionalTotalPagination import NO_TOTAL_PARAM

from .Fields import Fields

ALBUM_YEAR = f"{ModelFields.ALBUM}__{AlbumFields.YEAR}"
ORDERINGS = {
    "title": F(ModelFields.TITLE),
    # The recording's MusicBrainz first-release year, else its album's (a free-text column, so only four-digit years cast).
    "albumYear": Coalesce(
        F(ModelFields.FIRST_RELEASE_YEAR),
        Case(When(**{f"{ALBUM_YEAR}__regex": r"^[0-9]{4}$"}, then=Cast(ALBUM_YEAR, IntegerField()))),
    ),
}
DEFAULT_ORDERING = F(ModelFields.CREATED_ON)  # the viewset's default, see AppModelViewSet.queryset
SORT_KEY = "sort_key"


class RecordingFilterSet(PrivateUniqueResourceFilterSet):
    allowed_non_filter_params = PrivateUniqueResourceFilterSet.allowed_non_filter_params | {NO_TOTAL_PARAM}

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
    playable = BooleanFilter(method="filter_playable")
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
        # Ids are materialized: an OR with a subquery keeps Postgres off the genre index (seq scan over all recordings).
        descendants = CriteriaLineageRel.objects.filter(ascendant=value).values_list("descendant", flat=True)
        return queryset.filter(genre__in=[value, *descendants])

    def filter_playable(self, queryset: QuerySet[Recording], name: str, value: bool) -> QuerySet[Recording]:
        # Same predicate as TrackManager._is_playable.
        playable = Q(**{f"{ModelFields.YOUTUBE_VIDEO_ID}__isnull": False, "youtube_unplayable_reason__isnull": True})
        return queryset.filter(playable if value else ~playable)

    def filter_from(self, queryset: QuerySet[Recording], name: str, value) -> QuerySet[Recording]:
        # Applied in filter_queryset, once the other filters and the ordering it pages through are known.
        return queryset

    def filter_ordering(self, queryset: QuerySet[Recording], name: str, value: str) -> QuerySet[Recording]:
        field = ORDERINGS[value.lstrip("-")]
        descending = value.startswith("-")
        # Album-less recordings last either way; pk tie-breaker so OFFSET pages over tied rows neither repeat nor skip.
        return queryset.order_by(
            field.desc(nulls_last=True) if descending else field.asc(nulls_last=True),
            "-pk" if descending else "pk",
        )

    def filter_queryset(self, queryset: QuerySet[Recording]) -> QuerySet[Recording]:
        queryset = super().filter_queryset(queryset)
        anchor_uuid = self.form.cleaned_data.get(Fields.FROM)
        if anchor_uuid is None:
            return queryset
        ordering = self.form.cleaned_data.get("ordering")
        key = ORDERINGS[ordering.lstrip("-")] if ordering else DEFAULT_ORDERING
        return self._at_or_after(
            queryset.annotate(**{SORT_KEY: key}), anchor_uuid, bool(ordering and ordering[0] == "-")
        )

    @staticmethod
    def _at_or_after(queryset: QuerySet[Recording], anchor_uuid, descending: bool) -> QuerySet[Recording]:
        """`from`: the rows at or after the anchor in the active ordering (sort key nulls last, then pk), anchor
        included; 404 if the anchor isn't among the filtered rows."""
        # One query: an exists() check then a fetch could 500 if the anchor vanished in between.
        values = list(queryset.filter(pk=anchor_uuid).values_list(SORT_KEY, flat=True)[:1])
        if not values:
            raise NotFound(f"Recording {anchor_uuid} is not in this list.")
        value = values[0]
        after, pk_from = ("lt", "lte") if descending else ("gt", "gte")
        null_tail = Q(**{f"{SORT_KEY}__isnull": True})
        if value is None:
            return queryset.filter(null_tail, **{f"pk__{pk_from}": anchor_uuid})
        return queryset.filter(
            Q(**{f"{SORT_KEY}__{after}": value}) | Q(**{SORT_KEY: value, f"pk__{pk_from}": anchor_uuid}) | null_tail
        )


# `from` is a Python keyword, so it can't be declared as a class attribute.
RecordingFilterSet.base_filters[Fields.FROM] = UUIDFilter(method="filter_from")
