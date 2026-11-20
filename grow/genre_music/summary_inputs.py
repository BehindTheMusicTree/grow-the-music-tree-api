from dataclasses import dataclass

from django.db.models import Case, CharField, F, IntegerField, OuterRef, Subquery, UUIDField, Value, When
from django.db.models.functions import Coalesce
from the_music_tree_genre_kit.genre_graph.models import GenreGraphDataset

from grow.genre_graph.closure import FIRST_FREE_KIND, GraphClosure, GraphRowsReader, graph_union_sources, union_source
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.playlist.GenreCatalogueCount import GenreCatalogueCount
from grow.model.playlist.GenreMembershipCount import GenreMembershipCount


def catalogue_count_annotation():
    """Projected catalogue count per genre playlist, read inside the caller's statement.

    Sparse projection: a missing bucket means zero; the Genreless playlist (no criteria) reads the NULL bucket.
    """
    bucket = GenreCatalogueCount.objects.order_by()
    return Coalesce(
        Case(
            When(criteria_id__isnull=True, then=Subquery(bucket.filter(genre_id__isnull=True).values("tracks_count"))),
            default=Subquery(bucket.filter(genre_id=OuterRef("criteria_id")).values("tracks_count")),
            output_field=IntegerField(),
        ),
        Value(0),
        output_field=IntegerField(),
    )


_CATALOGUE, _OWNER, _MEMBERSHIP = range(FIRST_FREE_KIND, FIRST_FREE_KIND + 3)


@dataclass(frozen=True)
class SummaryInputs:
    closure: GraphClosure
    exact: dict
    owners: dict
    memberships: list


def summary_inputs(playlist_ids) -> SummaryInputs:
    """Dataset token, graph rows, buckets and memberships of the selected playlists, in one statement.

    A single statement is one snapshot, so the closure and the buckets it projects cannot diverge. When a
    closure is cached for the dataset token this statement sees, its graph rows are left out of the result.
    """
    reader = GraphRowsReader()
    sources = graph_union_sources()
    sources += [
        union_source(GenreCatalogueCount.objects.all(), _CATALOGUE, u_a="genre_id", u_int_a="tracks_count"),
        union_source(
            GenrePlaylist.objects.filter(user__isnull=True, pk__in=playlist_ids),
            _OWNER,
            u_a="pk",
            u_b="criteria_id",
        ),
        union_source(
            GenreMembershipCount.objects.filter(playlist_id__in=playlist_ids).annotate(
                owner=F("playlist__criteria_playlist__criteria_id")
            ),
            _MEMBERSHIP,
            u_a="playlist_id",
            u_b="owner",
            u_c="genre_id",
            u_int_a="tracks_count",
        ),
    ]
    exact, owners, memberships = {}, {}, []
    for kind, a, b, text, int_a, int_b, c in sources[0].union(*sources[1:], all=True):
        if reader.add(kind, a, b, text, int_a, int_b):
            continue
        if kind == _CATALOGUE:
            exact[a] = int_a
        elif kind == _OWNER:
            owners[a] = b
        else:
            memberships.append((a, b, c, int_a))
    closure = reader.closure()
    return SummaryInputs(closure, exact, owners, memberships)
