import logging
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.http import HttpResponse, HttpResponseNotModified
from django.utils.http import parse_etags
from redis.exceptions import RedisError
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from the_music_tree_api_kit.view.viewset.model.AppModelViewSet import UUID_PATTERN
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName
from the_music_tree_genre_kit.criteria.Fields import Fields as FilterFields
from the_music_tree_genre_kit.criteria.playlist.CriterialessPlaylistNames import CriterialessPlaylistNames
from the_music_tree_genre_kit.criteria.selection.coverage import (
    CriteriaCoverage,
    parse_coverage,
)
from the_music_tree_genre_kit.criteria.track_playlist_rel.tracks_count_annotation import tracks_count_annotation
from the_music_tree_genre_kit.filtering.set.criteria_playlist.CriteriaPlaylistFilterSet import CriteriaPlaylistFilterSet

from grow.genre_music.artist import artist_catalogue_counts, playlist_counts
from grow.genre_music.catalogue import GenreScopedCounts, catalogue_counts
from grow.genre_music.selection import parse_subgenres
from grow.genre_music.selection_query import selected_genres_query
from grow.model.artist.Artist import Artist
from grow.model.criteria.Criteria import Criteria
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.query_expressions import InSubquery
from grow.view.pagination.PlaylistTracksPagination import PlaylistTracksPagination
from grow.view.viewset.model.playlist.children.criteria.CriteriaPlaylistViewSet import CriteriaPlaylistViewSet

TREE_CACHE_TTL = timedelta(days=7).total_seconds()

logger = logging.getLogger(__name__)
_datetime = serializers.DateTimeField().to_representation


def _parents_by_child(m2m) -> tuple[dict, list]:
    parents: dict = {}
    edges = []
    for child_id, parent_id, uuid, name in m2m.through.objects.order_by(
        "from_criteria_id", "to_criteria_id"
    ).values_list("from_criteria_id", "to_criteria_id", "to_criteria__uuid", "to_criteria___name"):
        parents.setdefault(child_id, []).append({"uuid": uuid, "name": name})
        edges.append((parent_id, child_id))
    return parents, edges


def _tree_rows(queryset, artist_id: UUID | None = None) -> list[dict]:
    """CriteriaPlaylistSimpleSerializer's output from plain .values() rows: hydrating ~1.7k model graphs cost ~2s."""
    additional, extra_edges = _parents_by_child(Criteria.additional_primary_parents)
    secondary, _ = _parents_by_child(Criteria.secondary_parents)
    playlists = list(
        queryset.annotate(tracks_count=tracks_count_annotation()).values(
            "uuid",
            "created_on",
            "updated_on",
            "tracks_count",
            "views_count",
            "criteria_id",
            "criteria__uuid",
            "criteria___name",
            "criteria__created_on",
            "criteria__summary",
            "criteria__tree_name",
            "criteria__parent_id",
            "criteria__parent__uuid",
            "criteria__parent___name",
            "criteria__parent__criteria_playlist__uuid",
            "criteria__root___name",
            "criteria__root__criteria_playlist__uuid",
            "criteria__genre__side",
            "criteria__genre__wikidata_id",
            "criteria__genre__is_unaccepted_root",
            "criteria__genre__is_umbrella",
            "criteria__genre__scene",
        )
    )
    if artist_id is not None:
        songs_counts = artist_catalogue_counts(artist_id)
    else:
        all_genres = list(
            GenrePlaylist.objects.filter(user__isnull=True).values_list(
                "criteria_id", "direct_songs_count", "criteria__tree_name", "criteria__parent_id"
            )
        )
        trees = {genre: tree for genre, _, tree, _ in all_genres if genre is not None}
        edges = [(parent, genre) for genre, _, _, parent in all_genres if genre is not None and parent in trees]
        edges.extend((parent, child) for parent, child in extra_edges if parent in trees and child in trees)
        songs_counts = catalogue_counts({genre: count for genre, count, _, _ in all_genres}, (trees, edges))
    graph = None if artist_id is not None else (trees, edges)
    membership_counts = playlist_counts(artist_id, graph)
    rows = []
    for r in playlists:
        criteria_id = r["criteria_id"]
        name = r["criteria___name"] if criteria_id else CriterialessPlaylistNames.GENRE
        criteria = parent = None
        root = {"uuid": r["uuid"], "name": name}
        if criteria_id:
            criteria_parent = None
            if r["criteria__parent_id"]:
                criteria_parent = {"uuid": r["criteria__parent__uuid"], "name": r["criteria__parent___name"]}
                parent = {"uuid": r["criteria__parent__criteria_playlist__uuid"], "name": r["criteria__parent___name"]}
                root = {"uuid": r["criteria__root__criteria_playlist__uuid"], "name": r["criteria__root___name"]}
            criteria = {
                "uuid": r["criteria__uuid"],
                "name": name,
                "parent": criteria_parent,
                "created_on": _datetime(r["criteria__created_on"]),
                "side": r["criteria__genre__side"],
                "wikidata_id": r["criteria__genre__wikidata_id"],
                "summary": r["criteria__summary"],
                "tree_name": r["criteria__tree_name"],
                "primary_parents": ([criteria_parent] if criteria_parent else []) + additional.get(criteria_id, []),
                "secondary_parents": secondary.get(criteria_id, []),
            }
        rows.append(
            {
                "uuid": r["uuid"],
                "name": name,
                "criteria": criteria,
                "parent": parent,
                "root": root,
                "tracks_count": r["tracks_count"],
                "views_count": r["views_count"],
                "songs_count": songs_counts[criteria_id].default_count,
                "catalogue": {
                    "genre_only_tracks_count": songs_counts[criteria_id].genre_only_tracks_count,
                    "genre_and_subgenres_tracks_count": songs_counts[criteria_id].genre_and_subgenres_tracks_count,
                },
                "is_unaccepted_root": bool(r["criteria__genre__is_unaccepted_root"]),
                "is_umbrella": bool(r["criteria__genre__is_umbrella"]),
                "scene": r["criteria__genre__scene"],
                "created_on": _datetime(r["created_on"]),
                "updated_on": _datetime(r["updated_on"]),
            }
        )
    for row in rows:
        counts = membership_counts.get(row["uuid"])
        if counts is None:
            empty_scopes = {"all": 0}
            if row["criteria"] and row["criteria"]["tree_name"] == "canonical":
                empty_scopes.update(canonical=0, regional=0)
            counts = GenreScopedCounts(0, empty_scopes)
        row["genre_only_tracks_count"] = counts.genre_only_tracks_count
        row["genre_and_subgenres_tracks_count"] = counts.genre_and_subgenres_tracks_count
        row["tracks_count"] = counts.default_count
        if artist_id is not None:
            del row["views_count"]
    if artist_id is not None:
        kept = {
            row["uuid"]
            for row in rows
            if row["catalogue"]["genre_and_subgenres_tracks_count"]["all"] > 0
            or (row["name"] == "Mainstream Pop" and row["parent"] is None)
        }
        core = {row["uuid"] for row in rows if row["uuid"] in kept and row["name"] == "Core electronic"}
        kept.update(row["uuid"] for row in rows if row["parent"] and row["parent"]["uuid"] in core)
        rows = [row for row in rows if row["uuid"] in kept]
    return rows


class GenrePlaylistViewSet(CriteriaPlaylistViewSet):
    def __init__(self, **kwargs):
        super().__init__(model_class=GenrePlaylist, **kwargs)

    @action(detail=True, methods=["get"], url_path="tracks", pagination_class=PlaylistTracksPagination)
    def tracks(self, request, *args, **kwargs):
        return super().tracks(request, *args, **kwargs)

    def get_object(self):
        if self.action != "tracks" or not UUID_PATTERN.fullmatch(self.kwargs["pk"]):
            return super().get_object()
        # Scope validation needs the tree identity, loaded with the playlist rather than in
        # a separate graph query. Keep coverage parameters out of playlist identity lookup.
        playlist = get_object_or_404(self.get_queryset().select_related("criteria"), pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, playlist)
        return playlist

    def get_playlist_song_queryset(self, playlist):
        coverage = parse_coverage(self.request.query_params.get("coverage"))
        queryset = super().get_playlist_song_queryset(playlist)
        if playlist.criteria_id is None:
            if self.request.query_params.get("coverage") is not None:
                raise ValidationError({"coverage": "Genreless has no coverage selection."})
            if self.request.query_params.get("subgenres") is not None:
                raise ValidationError({"subgenres": "Genreless has no subgenres."})
            queryset = queryset.filter(genre_id__isnull=True)
        elif coverage == CriteriaCoverage.ONLY:
            parse_subgenres(self.request.query_params.get("subgenres"), coverage, "canonical")
            queryset = queryset.filter(genre_id=playlist.criteria_id)
        else:
            scope = parse_subgenres(self.request.query_params.get("subgenres"), coverage, playlist.criteria.tree_name)
            selected = selected_genres_query(
                playlist.criteria_id, playlist.criteria.tree_name, scope, using=queryset.db
            )
            queryset = queryset.filter(InSubquery(F("genre_id"), selected))
        artist_id = self.request.query_params.get("artist")
        if artist_id is not None:
            try:
                artist_uuid = UUID(artist_id)
            except ValueError:
                raise ValidationError({"artist": "Must be an artist UUID."}) from None
            if not Artist.objects.filter(user__isnull=True, uuid=artist_uuid).exists():
                raise NotFound("Artist not found.")
            queryset = queryset.filter(artists=artist_uuid)
        return queryset

    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request: Request) -> HttpResponse:
        """Whole genre tree, unpaginated, cached under the DB-trigger-maintained GenreTreeVersion token."""
        tree_name = request.query_params.get(FilterFields.TREE_NAME)
        if tree_name not in CriteriaTreeName.values:
            raise ValidationError({FilterFields.TREE_NAME: f"Required, one of {CriteriaTreeName.values}"})

        artist = request.query_params.get("artist")
        if artist is not None:
            try:
                artist_id = UUID(artist)
            except ValueError:
                raise ValidationError({"artist": "Must be an artist UUID."}) from None
            if not Artist.objects.filter(user__isnull=True, uuid=artist_id).exists():
                raise NotFound("Artist not found.")
            queryset = CriteriaPlaylistFilterSet(queryset=self.get_queryset()).filter_tree_name(
                self.get_queryset(), FilterFields.TREE_NAME, tree_name
            )
            body = self.get_renderers()[0].render(_tree_rows(queryset, artist_id))
            return HttpResponse(body, content_type="application/json", headers={"Cache-Control": "no-store"})

        token = GenreTreeVersion.current_token()
        version = f"scoped-v2-{tree_name}-{settings.GIT_COMMIT}-{token}"
        etag = f'"{version}"'
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if etag in (e.removeprefix("W/") for e in parse_etags(request.headers.get("If-None-Match", ""))):
            return HttpResponseNotModified(headers=headers)

        cache_key = f"genre-tree:{version}"
        try:
            body = cache.get(cache_key)
        except RedisError:
            logger.warning("Genre tree cache unavailable, serving uncached", exc_info=True)
            body = None
        if body is None:
            queryset = CriteriaPlaylistFilterSet(queryset=self.get_queryset()).filter_tree_name(
                self.get_queryset(), FilterFields.TREE_NAME, tree_name
            )
            body = self.get_renderers()[0].render(_tree_rows(queryset))
            try:
                cache.set(cache_key, body, TREE_CACHE_TTL)
            except RedisError:
                logger.warning("Genre tree cache unavailable, response not cached", exc_info=True)
        return HttpResponse(body, content_type="application/json", headers=headers)
