from dataclasses import asdict
from functools import lru_cache

from rest_framework import serializers
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks

from grow.genre_music.artist import playlist_counts
from grow.genre_music.catalogue import GenreScopedCounts, catalogue_counts
from grow.genre_music.selection import all_genre_selections
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist


@lru_cache(maxsize=1)
def _catalogue_projection(rows: tuple, playlist_ids: frozenset):
    # Key the pure projection by every source value, not a process-local version token:
    # uncommitted reads and rollbacks must never poison another request's counts.
    trees = {}
    exact = {}
    selected = set()
    selected_rows = {}
    for playlist, genre, count, tree, _, _ in rows:
        exact[genre] = count
        if genre is not None:
            trees[genre] = tree
        if playlist in playlist_ids:
            selected_rows[playlist] = genre, tree
            if genre is not None:
                selected.add(genre)
    edges = {
        (parent, genre)
        for _, genre, _, _, direct, extra in rows
        for parent in (direct, extra)
        if parent is not None and parent in trees and genre is not None
    }
    graph = trees, edges
    selections = all_genre_selections(trees, edges, genres=selected)
    catalogue = catalogue_counts(exact, graph, selections=selections)
    return graph, selections, catalogue, selected_rows


def genre_playlist_summaries(playlist_ids) -> dict:
    """Two bounded queries for catalogue and actual membership summaries for all genres."""
    playlist_ids = frozenset(playlist_ids)
    rows = tuple(
        GenrePlaylist.objects.filter(user__isnull=True)
        .order_by("pk", "criteria__additional_primary_parents__pk")
        .values_list(
            "pk",
            "criteria_id",
            "direct_songs_count",
            "criteria__tree_name",
            "criteria__parent_id",
            "criteria__additional_primary_parents__pk",
        )
    )
    graph, selections, catalogue, selected_rows = _catalogue_projection(rows, playlist_ids)
    memberships = playlist_counts(None, graph, playlist_ids=playlist_ids, selections=selections)
    summaries = {}
    for playlist, (genre, tree) in selected_rows.items():
        scopes = {"canonical": 0, "regional": 0, "all": 0} if tree == "canonical" else {"all": 0}
        counts = memberships.get(playlist, GenreScopedCounts(0, scopes))
        summaries[playlist] = {
            **asdict(counts),
            "tracks_count": counts.default_count,
            "catalogue": asdict(catalogue[genre]),
        }
    return summaries


class GenrePlaylistSummaryMixin:
    def to_representation(self, instance):
        data = super().to_representation(instance)
        criteria_playlist = (
            instance if isinstance(instance, CriteriaPlaylist) else getattr(instance, "criteria_playlist", None)
        )
        if (
            criteria_playlist is None
            or criteria_playlist.type_id != int(CriteriaTypePks.GENRE)
            or instance.user_id is not None
        ):
            return data
        # Minimum identity serializers remain small. Full playlist representations share
        # one batched summary map through the DRF request context, including nested output.
        key = "genre_playlist_summaries"
        if key not in self.context:
            instances = self.parent.instance if isinstance(self.parent, serializers.ListSerializer) else [instance]
            self.context[key] = genre_playlist_summaries({item.pk for item in instances})
        summary = self.context[key].get(instance.pk)
        if summary is not None:
            data.update(summary)
        return data
