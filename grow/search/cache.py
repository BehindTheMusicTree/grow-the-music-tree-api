import hashlib
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from django.core.cache import cache
from django.db import transaction

TTL_SECONDS = 3600


class SearchCache(StrEnum):
    ARTISTS = "artist-search"
    SONGS = "song-search"


def _version_key(namespace: SearchCache) -> str:
    return f"{namespace}-version"


def cached_search(
    namespace: SearchCache, query: str, params: tuple[Any, ...], compute: Callable[[], list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """The cached results of `compute`, which runs and is cached on a miss."""
    # The version is read once: a write committing while `compute` runs bumps it, so its now-stale results land under
    # a key no later request reads, instead of under the new version.
    version = cache.get(_version_key(namespace), 0)
    digest = hashlib.sha1(query.strip().casefold().encode(), usedforsecurity=False).hexdigest()
    key = f"{namespace}:{version}:{':'.join(map(str, params))}:{digest}"
    payload = cache.get(key)
    if payload is None:
        payload = compute()
        cache.set(key, payload, TTL_SECONDS)
    return payload


def invalidate_search_cache(*namespaces: SearchCache) -> None:
    """Bumps each namespace's version (all of them by default), orphaning its cached results until their TTL."""
    for namespace in namespaces or tuple(SearchCache):
        cache.add(_version_key(namespace), 0, None)
        cache.incr(_version_key(namespace))


def on_track_deleted(**kwargs: Any) -> None:
    # The projection row goes with the song (ORM cascade), but nothing else would bump the cached results holding it.
    transaction.on_commit(lambda: invalidate_search_cache(SearchCache.SONGS))
