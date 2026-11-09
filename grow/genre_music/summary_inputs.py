from django.db.models import CharField, IntegerField, Subquery, UUIDField, Value

from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.playlist.GenreMembershipCount import GenreMembershipCount

_catalogue_rows: tuple[object, tuple] | None = None


def clear_summary_inputs_cache() -> None:
    global _catalogue_rows
    _catalogue_rows = None


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
    graph = GenrePlaylist.objects.filter(user__isnull=True).annotate(input_kind=Value(0), input_version=version)
    if cached is not None:
        graph = graph.exclude(input_version=cached[0])
    graph_rows = graph.order_by().values_list(
        "input_kind",
        "input_version",
        "pk",
        "criteria_id",
        "direct_songs_count",
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
    catalogue, memberships, token = [], [], None
    for kind, row_token, playlist, genre, count, tree, parent, extra in graph_rows.union(
        token_row, membership_rows, all=True
    ):
        if kind == 0:
            catalogue.append((playlist, genre, count, tree, parent, extra))
        elif kind == 1:
            token = row_token
        else:
            memberships.append((playlist, genre, parent, count))
    if token is None:
        raise GenreTreeVersion.DoesNotExist("Genre tree version singleton is missing")
    if cached is not None and cached[0] == token:
        rows = cached[1]
    else:
        rows = tuple(catalogue)
        _catalogue_rows = token, rows
    return rows, memberships
