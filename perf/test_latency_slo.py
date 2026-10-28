import statistics
import time

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from grow.model.artist.Artist import Artist
from grow.model.criteria.children.genre.Genre import Genre
from perf.conftest import largest_genre_playlist, mid_size_genre
from tests.utils.AppApiClient import AppApiClient

WARMUPS = 2
RUNS = 10

# Median ceilings in ms, ~2x the median measured on an Apple M-series laptop against postgres:16-alpine in Docker.
# Median, not p95: over back-to-back runs p95 is the single worst outlier (GC, noisy CI runners), not a tail.
SLO_MS = {
    "genre-playlist-list?page_size=30": 300,
    "genre-playlist-list?page_size=100": 400,
    "tag-playlist-list?page_size=100": 100,
    "playlist-list?page_size=100": 100,
    "genre-list?page_size=100": 200,
    "genre-playlist-detail (largest genre)": 100,
    "playlist-detail (largest genre)": 100,
    "genre-playlist-tracks?page_size=100 (largest genre)": 150,
    "artist-genre-counts (Canned Heat)": 150,
}


def _large_playlist(name: str) -> str:
    return reverse(name, kwargs={"pk": largest_genre_playlist().uuid})


def _largest_artist_genre_counts() -> str:
    artist = Artist.objects.get(_name="Canned Heat", user__isnull=True)
    return reverse("artist-genre-counts", kwargs={"pk": artist.uuid})


PATHS = {
    "genre-playlist-list?page_size=30": lambda: (reverse("genre-playlist-list"), {"page_size": 30}),
    "genre-playlist-list?page_size=100": lambda: (reverse("genre-playlist-list"), {"page_size": 100}),
    "tag-playlist-list?page_size=100": lambda: (reverse("tag-playlist-list"), {"page_size": 100}),
    "playlist-list?page_size=100": lambda: (reverse("playlist-list"), {"page_size": 100}),
    "genre-list?page_size=100": lambda: (reverse("genre-list"), {"page_size": 100}),
    "genre-playlist-detail (largest genre)": lambda: (_large_playlist("genre-playlist-detail"), {}),
    "playlist-detail (largest genre)": lambda: (_large_playlist("playlist-detail"), {}),
    "genre-playlist-tracks?page_size=100 (largest genre)": lambda: (
        _large_playlist("genre-playlist-tracks"),
        {"page_size": 100},
    ),
    "artist-genre-counts (Canned Heat)": lambda: (_largest_artist_genre_counts(), {}),
}


@pytest.mark.django_db
@pytest.mark.parametrize("scenario", SLO_MS)
def test_median_latency_within_slo(scenario):
    path, params = PATHS[scenario]()
    client = AppApiClient()
    for _ in range(WARMUPS):
        assert client.get(path, params).status_code == status.HTTP_200_OK

    timings = []
    for _ in range(RUNS):
        start = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            client.get(path, params)
        timings.append((time.perf_counter() - start) * 1000)

    p50 = statistics.median(timings)
    p95 = statistics.quantiles(timings, n=20)[-1]
    print(f"\n{scenario:<38} queries={len(queries.captured_queries):>5}  p50={p50:8.1f}ms  p95={p95:8.1f}ms")
    assert p50 <= SLO_MS[scenario]


# Cold serializes the whole ~1.7k-row tree; warm and not-modified only read the version token.
TREE_SLO_MS = {"cold": 2400, "warm": 20, "not-modified": 20}


@pytest.mark.django_db
@pytest.mark.parametrize("mode", TREE_SLO_MS)
def test_genre_tree_median_latency_within_slo(mode):
    client = AppApiClient()
    path, params = reverse("genre-playlist-tree"), {"tree_name": "canonical"}
    etag = client.get(path, params)["ETag"]
    headers = {"HTTP_IF_NONE_MATCH": etag} if mode == "not-modified" else {}

    timings = []
    for _ in range(RUNS):
        if mode == "cold":
            cache.clear()
        start = time.perf_counter()
        response = client.get(path, params, **headers)
        timings.append((time.perf_counter() - start) * 1000)
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_304_NOT_MODIFIED)

    p50 = statistics.median(timings)
    print(f"\ngenre-playlist-tree ({mode})".ljust(39) + f"p50={p50:8.1f}ms")
    assert p50 <= TREE_SLO_MS[mode]


# Reparenting a ~250-track genre under the biggest playlist's genre timed out (gunicorn 30s) before the set-based track moves.
REPARENT_SLO_MS = 2400


@pytest.mark.django_db
def test_genre_reparent_median_latency_within_slo():
    client = AppApiClient()
    target = largest_genre_playlist().criteria
    moved = mid_size_genre(exclude=target)
    original_parent = moved.parent
    url = reverse("genre-detail", kwargs={"pk": moved.uuid})

    timings = []
    for _ in range(3):
        for parent in (target, original_parent):
            start = time.perf_counter()
            response = client.put(url, {"parent": str(parent.uuid)})
            timings.append((time.perf_counter() - start) * 1000)
            assert response.status_code == status.HTTP_200_OK, response.content[:500]
    assert Genre.objects.get(pk=moved.pk).parent_id == original_parent.pk

    p50 = statistics.median(timings)
    print(f"\ngenre reparent ({moved.name})".ljust(39) + f"p50={p50:8.1f}ms  max={max(timings):8.1f}ms")
    assert p50 <= REPARENT_SLO_MS
