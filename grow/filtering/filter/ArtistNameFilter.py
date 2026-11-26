from django.core.exceptions import ImproperlyConfigured
from django.db.models import Exists, F, Func, OuterRef, QuerySet, TextField, Value
from the_music_tree_api_kit.filtering.filter.char.RelatedObjectCharFilter import RelatedObjectCharFilter

from grow.model.artist.Artist import Artist
from grow.model.artist.Fields import Fields as ArtistFields

# Above either bound, matches are dense enough that walking the rows in page order finds a page quickly.
MAX_LISTED_ARTISTS = 1_000
MAX_LISTED_SONGS = 10_000


def _fold(expression: F | Value) -> Func:
    return Func(expression, function="grow_search_norm", output_field=TextField())


class ArtistNameFilter(RelatedObjectCharFilter):
    """Matches rows by a substring of a credited artist's accent- and case-folded name, one row per match.

    A rare name is resolved to its artists first through the `folded_name` trigram index, so the row query filters on
    an explicit id list whose cardinality the planner can see. A broad name keeps the walk in page order, matched on
    the unindexed expression: Postgres estimates any `folded_name LIKE` at a flat ~200 artists, and on that column it
    would pick the artist-first plan for names crediting tens of thousands of songs (a timeout on prod-scale data).
    """

    def __init__(self, field_name: str, field_name_public: str) -> None:
        super().__init__(
            primary_field=ArtistFields.NAME_INTERNAL,
            field_name=field_name,
            field_name_public=field_name_public,
            lookup_expr="contains",
        )

    def filter(self, qs: QuerySet, value: str | None) -> QuerySet:
        if not value:
            return super().filter(qs, value)

        relation = qs.model._meta.get_field(self.field_name)
        if not relation.many_to_many or relation.auto_created:
            raise ImproperlyConfigured(f"{self.field_name} is not a forward many-to-many relation to artists.")
        through = relation.remote_field.through
        source_name = relation.m2m_field_name()
        artist_name = relation.m2m_reverse_field_name()
        credits = through._base_manager.filter(
            **{source_name: OuterRef(through._meta.get_field(source_name).target_field.attname)}
        )

        folded = _fold(Value(value))
        matches = list(
            Artist._base_manager.filter(folded_name__contains=folded).values_list("pk", "recording_count")[
                : MAX_LISTED_ARTISTS + 1
            ]
        )
        if not matches:
            return qs.none()
        # recording_count only picks the plan; the id list itself is exact.
        if len(matches) <= MAX_LISTED_ARTISTS and sum(count for _, count in matches) <= MAX_LISTED_SONGS:
            return qs.filter(Exists(credits.filter(**{f"{artist_name}__in": [pk for pk, _ in matches]})))
        return qs.filter(
            Exists(
                credits.alias(credited_folded_name=_fold(F(f"{artist_name}__{self.primary_field}"))).filter(
                    credited_folded_name__contains=folded
                )
            )
        )
