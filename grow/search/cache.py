import hashlib
from enum import StrEnum
from typing import Any

from django.core.cache import cache

TTL_SECONDS = 3600


class SearchCache(StrEnum):
    ARTISTS = "artist-search"
    SONGS = "song-search"


def _version_key(namespace: SearchCache) -> str:
    return f"{namespace}-version"


def _key(namespace: SearchCache, query: str, params: tuple[Any, ...]) -> str:
    version = cache.get(_version_key(namespace), 0)
    digest = hashlib.sha1(query.strip().casefold().encode(), usedforsecurity=False).hexdigest()
    return f"{namespace}:{version}:{':'.join(map(str, params))}:{digest}"


def get_cached_search(namespace: SearchCache, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]] | None:
    return cache.get(_key(namespace, query, params))


def set_cached_search(
    namespace: SearchCache, query: str, params: tuple[Any, ...], payload: list[dict[str, Any]]
) -> None:
    cache.set(_key(namespace, query, params), payload, TTL_SECONDS)


def invalidate_search_cache(*namespaces: SearchCache) -> None:
    """Bumps each namespace's version (all of them by default), orphaning its cached results until their TTL."""
    for namespace in namespaces or tuple(SearchCache):
        cache.add(_version_key(namespace), 0, None)
        cache.incr(_version_key(namespace))
