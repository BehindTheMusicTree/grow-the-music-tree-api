import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotModified
from django.utils.http import parse_etags
from redis.exceptions import RedisError
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName
from the_music_tree_genre_kit.criteria.Fields import Fields as FilterFields
from the_music_tree_genre_kit.criteria.playlist.CriterialessPlaylistNames import CriterialessPlaylistNames
from the_music_tree_genre_kit.criteria.track_playlist_rel.tracks_count_annotation import tracks_count_annotation
from the_music_tree_genre_kit.filtering.set.criteria_playlist.CriteriaPlaylistFilterSet import CriteriaPlaylistFilterSet

from grow.model.criteria.Criteria import Criteria
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.view.viewset.model.playlist.children.criteria.CriteriaPlaylistViewSet import CriteriaPlaylistViewSet

TREE_CACHE_TTL = timedelta(days=7).total_seconds()

logger = logging.getLogger(__name__)
_datetime = serializers.DateTimeField().to_representation


def _parents_by_child(m2m) -> dict[int, list[dict]]:
    # Unique (from, to) index order, which is what the unordered prefetch returned in practice.
    parents: dict[int, list[dict]] = {}
    for child_id, uuid, name in m2m.through.objects.order_by("from_criteria_id", "to_criteria_id").values_list(
        "from_criteria_id", "to_criteria__uuid", "to_criteria___name"
    ):
        parents.setdefault(child_id, []).append({"uuid": uuid, "name": name})
    return parents


def _tree_rows(queryset) -> list[dict]:
    """CriteriaPlaylistSimpleSerializer's output from plain .values() rows: hydrating ~1.7k model graphs cost ~2s."""
    additional = _parents_by_child(Criteria.additional_primary_parents)
    secondary = _parents_by_child(Criteria.secondary_parents)
    rows = []
    for r in queryset.annotate(tracks_count=tracks_count_annotation()).values(
        "uuid",
        "created_on",
        "updated_on",
        "tracks_count",
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
    ):
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
                "is_unaccepted_root": bool(r["criteria__genre__is_unaccepted_root"]),
                "is_umbrella": bool(r["criteria__genre__is_umbrella"]),
                "created_on": _datetime(r["created_on"]),
                "updated_on": _datetime(r["updated_on"]),
            }
        )
    return rows


class GenrePlaylistViewSet(CriteriaPlaylistViewSet):
    def __init__(self, **kwargs):
        super().__init__(model_class=GenrePlaylist, **kwargs)

    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request: Request) -> HttpResponse:
        """Whole genre tree, unpaginated, cached under the DB-trigger-maintained GenreTreeVersion token."""
        tree_name = request.query_params.get(FilterFields.TREE_NAME)
        if tree_name not in CriteriaTreeName.values:
            raise ValidationError({FilterFields.TREE_NAME: f"Required, one of {CriteriaTreeName.values}"})

        token = GenreTreeVersion.current_token()
        version = f"{tree_name}-{settings.GIT_COMMIT}-{token}"
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
