from django.db.models import Case, CharField, IntegerField, OuterRef, Subquery, UUIDField, Value, When
from django.db.models.functions import Coalesce

from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.playlist.GenreCatalogueCount import GenreCatalogueCount
from grow.model.playlist.GenreMembershipCount import GenreMembershipCount

_catalogue_rows: tuple[object, tuple] | None = None


def clear_summary_inputs_cache() -> None:
    global _catalogue_rows
    _catalogue_rows = None


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


def summary_inputs(playlist_ids):
    """Read version, catalogue/graph and selected memberships in one statement snapshot.

    A token identifies committed source contents, including catalogue counters.
    Cached inputs can replace graph rows only when this statement sees that same
    token. A writer's uncommitted random token disappears on rollback, so it
    cannot expose those cached contents to another transaction.
    """
    global _catalogue_rows
    cached = _catalogue_rows
    version = Subquery(GenreTreeVersion.objects.filter(pk=1).values("token"))
    null_uuid = Value(None, output_field=UUIDField())
    graph = GenrePlaylist.objects.filter(user__isnull=True).annotate(
        input_kind=Value(0), input_version=version, catalogue_count=Value(0, output_field=IntegerField())
    )
    if cached is not None:
        graph = graph.exclude(input_version=cached[0])
    graph_rows = graph.order_by().values_list(
        "input_kind",
        "input_version",
        "pk",
        "criteria_id",
        "catalogue_count",
        "criteria__tree_name",
        "criteria__parent_id",
        "criteria__additional_primary_parents__pk",
    )
    token_row = (
        GenreTreeVersion.objects.filter(pk=1)
        .annotate(
            input_kind=Value(1),
            playlist=null_uuid,
            genre=null_uuid,
            count=Value(0, output_field=IntegerField()),
            tree=Value("", output_field=CharField()),
            parent=null_uuid,
            extra=null_uuid,
        )
        .order_by()
        .values_list("input_kind", "token", "playlist", "genre", "count", "tree", "parent", "extra")
    )
    membership_rows = (
        GenreMembershipCount.objects.filter(playlist_id__in=playlist_ids)
        .annotate(
            input_kind=Value(2),
            input_version=version,
            tree=Value("", output_field=CharField()),
            extra=null_uuid,
        )
        .order_by()
        .values_list(
            "input_kind",
            "input_version",
            "playlist_id",
            "playlist__criteria_playlist__criteria_id",
            "tracks_count",
            "tree",
            "genre_id",
            "extra",
        )
    )
    catalogue_rows = (
        GenreCatalogueCount.objects.annotate(
            input_kind=Value(3),
            input_version=version,
            playlist=null_uuid,
            tree=Value("", output_field=CharField()),
            parent=null_uuid,
            extra=null_uuid,
        )
        .order_by()
        .values_list("input_kind", "input_version", "playlist", "genre_id", "tracks_count", "tree", "parent", "extra")
    )
    # Read sparse buckets once, instead of a correlated lookup for every graph row.
    catalogue, memberships, counts, token = [], [], {}, None
    for kind, row_token, playlist, genre, count, tree, parent, extra in graph_rows.union(
        token_row, membership_rows, catalogue_rows, all=True
    ):
        if kind == 0:
            catalogue.append((playlist, genre, count, tree, parent, extra))
        elif kind == 1:
            token = row_token
        elif kind == 3:
            counts[genre] = count
        else:
            memberships.append((playlist, genre, parent, count))
    if token is None:
        raise GenreTreeVersion.DoesNotExist("Genre tree version singleton is missing")
    if cached is not None and cached[0] == token:
        rows = cached[1]
    else:
        rows = tuple(
            (playlist, genre, counts.get(genre, 0), tree, parent, extra)
            for playlist, genre, _, tree, parent, extra in catalogue
        )
        _catalogue_rows = token, rows
    return rows, memberships
