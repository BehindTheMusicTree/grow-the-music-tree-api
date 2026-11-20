from dataclasses import asdict

from django.db.models import Case, IntegerField, Value, When
from rest_framework import serializers
from the_music_tree_genre_kit.criteria.track_playlist_rel.tracks_count_annotation import tracks_count_annotation
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks
from the_music_tree_genre_kit.genre_graph.storage import graph_read_snapshot

from grow.genre_music.artist import playlist_counts_from_rows
from grow.genre_music.catalogue import GenreScopedCounts, catalogue_counts
from grow.genre_music.summary_inputs import summary_inputs
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist


def playlist_tracks_count_annotation():
    # Genre summaries replace this field from exact membership buckets; avoid
    # scanning their full relation sets for a value that is immediately discarded.
    return Case(
        When(criteria_playlist__type_id=int(CriteriaTypePks.GENRE), user__isnull=True, then=Value(0)),
        default=tracks_count_annotation(),
        output_field=IntegerField(),
    )


def genre_playlist_summaries(playlist_ids) -> dict:
    """Catalogue and actual membership summaries, read from one graph snapshot."""
    playlist_ids = frozenset(playlist_ids)
    with graph_read_snapshot():
        inputs = summary_inputs(playlist_ids)
        closure, exact, owners = inputs.closure, inputs.exact, inputs.owners
        selected = {genre for genre in owners.values() if genre is not None}
        catalogue = catalogue_counts(exact, closure, genres=selected)
        memberships = playlist_counts_from_rows(inputs.memberships, closure)
    summaries = {}
    for playlist, genre in owners.items():
        scopes = (
            {"canonical": 0, "regional": 0, "all": 0} if closure.tree_names.get(genre) == "canonical" else {"all": 0}
        )
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
