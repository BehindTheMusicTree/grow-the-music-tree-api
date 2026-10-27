import hashlib
from typing import Any

from django.core.cache import cache

VERSION_KEY = "artist-search-version"
TTL_SECONDS = 3600


def _key(query: str, limit: int) -> str:
    version = cache.get(VERSION_KEY, 0)
    digest = hashlib.sha1(query.strip().casefold().encode(), usedforsecurity=False).hexdigest()
    return f"artist-search:{version}:{limit}:{digest}"


def get_cached_search(query: str, limit: int) -> list[dict[str, Any]] | None:
    return cache.get(_key(query, limit))


def set_cached_search(query: str, limit: int, payload: list[dict[str, Any]]) -> None:
    cache.set(_key(query, limit), payload, TTL_SECONDS)


def invalidate_search_cache() -> None:
    cache.add(VERSION_KEY, 0, None)
    cache.incr(VERSION_KEY)
