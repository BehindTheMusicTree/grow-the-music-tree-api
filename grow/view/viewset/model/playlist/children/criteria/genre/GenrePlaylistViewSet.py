import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotModified
from django.utils.http import parse_etags
from redis.exceptions import RedisError
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName

from grow.filtering.set.playlist.children.criteria.CriteriaPlaylistFilterSet import CriteriaPlaylistFilterSet
from grow.filtering.set.playlist.children.criteria.Fields import Fields as FilterFields
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.serializer.model.playlist.children.criteria.output.simple import CriteriaPlaylistSimpleSerializer
from grow.view.viewset.model.playlist.children.criteria.CriteriaPlaylistViewSet import CriteriaPlaylistViewSet

TREE_CACHE_TTL = timedelta(days=7).total_seconds()

logger = logging.getLogger(__name__)


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
        if etag in parse_etags(request.headers.get("If-None-Match", "")):
            return HttpResponseNotModified(headers=headers)

        cache_key = f"genre-tree:{version}"
        try:
            body = cache.get(cache_key)
        except RedisError:
            logger.warning("Genre tree cache unavailable, serving uncached", exc_info=True)
            body = None
        if body is None:
            queryset = CriteriaPlaylistFilterSet().filter_tree_name(
                self.get_queryset(), FilterFields.TREE_NAME, tree_name
            )
            data = CriteriaPlaylistSimpleSerializer(
                CriteriaPlaylistSimpleSerializer.setup_queryset(queryset), many=True
            ).data
            body = self.get_renderers()[0].render(data)
            try:
                cache.set(cache_key, body, TREE_CACHE_TTL)
            except RedisError:
                logger.warning("Genre tree cache unavailable, response not cached", exc_info=True)
        return HttpResponse(body, content_type="application/json", headers=headers)
