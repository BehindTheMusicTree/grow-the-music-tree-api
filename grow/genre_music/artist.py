from collections import defaultdict
from uuid import UUID

from django.db.models import Count
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks

from grow.genre_music.catalogue import GenreScopedCounts, catalogue_counts
from grow.genre_music.selection import (
    GenreTreeSnapshot,
    all_genre_selections,
    genre_graph,
    genre_tree_snapshot,
    primary_ancestors,
)
from grow.model.song.Song import Song


def artist_exact_counts(artist_id: UUID) -> dict:
    """The artist's canonical songs per assigned genre, None for genreless songs."""
    return dict(
        Song.objects.filter(user__isnull=True, artists=artist_id)
        .order_by()
        .values_list("genre_id")
        .annotate(count=Count("pk", distinct=True))
    )


def artist_nonzero_catalogue_counts(exact: dict, snapshot: GenreTreeSnapshot) -> dict:
    """Scoped counts for the only genres that can be nonzero: assigned genres and their primary ancestors."""
    affected = primary_ancestors(snapshot, (genre for genre in exact if genre is not None))
    selections = all_genre_selections(snapshot.tree_names, snapshot.primary_edges, genres=affected)
    return catalogue_counts(exact, (snapshot.tree_names, snapshot.primary_edges), selections=selections)


def artist_catalogue_counts(artist_id: UUID, snapshot: GenreTreeSnapshot | None = None) -> dict:
    """Scoped counts for every genre, zero-filled."""
    snapshot = snapshot if snapshot is not None else genre_tree_snapshot()
    counts = {
        genre: GenreScopedCounts(0, {"canonical": 0, "regional": 0, "all": 0} if tree == "canonical" else {"all": 0})
        for genre, tree in snapshot.tree_names.items()
    }
    counts.update(artist_nonzero_catalogue_counts(artist_exact_counts(artist_id), snapshot))
    return counts


def playlist_counts(
    artist_id: UUID | None, graph=None, playlist_id: UUID | None = None, *, playlist_ids=None, selections=None
) -> dict:
    queryset = TrackPlaylistRel.objects.filter(
        user__isnull=True,
        track__user__isnull=True,
        playlist__user__isnull=True,
        playlist__criteria_playlist__type_id=int(CriteriaTypePks.GENRE),
    )
    if artist_id is not None:
        queryset = queryset.filter(track__artists=artist_id)
    if playlist_id is not None:
        queryset = queryset.filter(playlist_id=playlist_id)
    if artist_id is None:
        from grow.model.playlist.GenreMembershipCount import GenreMembershipCount

        buckets = GenreMembershipCount.objects.all()
        if playlist_ids is not None:
            buckets = buckets.filter(playlist_id__in=playlist_ids)
        if playlist_id is not None:
            buckets = buckets.filter(playlist_id=playlist_id)
        rows = buckets.values_list(
            "playlist_id", "playlist__criteria_playlist__criteria_id", "genre_id", "tracks_count"
        )
    else:
        rows = (
            queryset.order_by()
            .values_list("playlist__uuid", "playlist__criteria_playlist__criteria_id", "track__genre_id")
            .annotate(count=Count("pk", distinct=True))
        )
    trees, edges = graph if graph is not None else genre_graph()
    return playlist_counts_from_rows(rows, (trees, edges), selections=selections)


def playlist_counts_from_rows(rows, graph, *, selections=None) -> dict:
    """Project already-loaded exact membership buckets without another database read."""
    grouped = defaultdict(dict)
    owners = {}
    for playlist, genre, track_genre, count in rows:
        grouped[playlist][track_genre] = count
        owners[playlist] = genre
    trees, edges = graph
    if selections is None:
        selections = all_genre_selections(
            trees, edges, genres={genre for genre in owners.values() if genre is not None}
        )
    result = {}
    for playlist, counts in grouped.items():
        genre = owners[playlist]
        direct = counts.get(genre, 0)
        if genre is None:
            values = {"all": direct}
        else:
            values = {
                scope.value: sum(counts[node] for node in counts.keys() & nodes)
                for scope, nodes in selections[genre].items()
            }
        result[playlist] = GenreScopedCounts(direct, values)
    return result
