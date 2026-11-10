import statistics
import time

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from grow.genre_music.selection import _selection_index
from grow.genre_music.summary import _catalogue_projection
from grow.genre_music.summary_inputs import clear_summary_inputs_cache
from grow.model.artist.Artist import Artist
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.children.tag.Tag import Tag
from grow.model.song.Song import Song
from perf.conftest import assert_within_slo, largest_genre_playlist, mid_size_genre
from tests.utils.AppApiClient import AppApiClient

WARMUPS = 2
RUNS = 10

# All ceilings below: 3x the slowest side's pooled p50 across five CI self-comparisons on 2026-11-07,
# rounded up to 10 ms (100 ms above 1 s). Postgres 16, pinned Gold fixtures; calibration links in README.
# Median, not p95: over back-to-back runs p95 is the single worst outlier (GC, noisy CI runners), not a tail.
SLO_MS = {
    "genre-playlist-list?page_size=30": 360,
    "genre-playlist-list?page_size=100": 470,
    "tag-playlist-list?page_size=100": 50,
    "playlist-list?page_size=100": 200,
    "genre-list?page_size=100": 140,
    "genre-playlist-detail (largest genre)": 140,
    "playlist-detail (largest genre)": 120,
    "genre-playlist-tracks?page_size=100 (largest genre)": 260,
    "artist-genre-counts (Canned Heat)": 30,
    # Provisional: 3x a single local p50 (326 / 59 ms), not yet pooled over CI self-comparisons like the rest.
    "genre-playlist-tracks (front: viewer FR, coverage+subgenres)": 990,
    "genre-playlist-tracks (front: viewer FR, genre_only)": 180,
}

VIEWER_TOKEN = "perf-viewer-token"
# The front always sends the trusted viewer headers, so regional policies are evaluated per row, not skipped.
VIEWER_HEADERS = {"HTTP_X_VIEWER_CONTEXT_TOKEN": VIEWER_TOKEN, "HTTP_X_VIEWER_COUNTRY": "FR"}
HEADERS = {
    "genre-playlist-tracks (front: viewer FR, coverage+subgenres)": VIEWER_HEADERS,
    "genre-playlist-tracks (front: viewer FR, genre_only)": VIEWER_HEADERS,
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
    "genre-playlist-tracks (front: viewer FR, coverage+subgenres)": lambda: (
        _large_playlist("genre-playlist-tracks"),
        {"page_size": 100, "coverage": "genre_and_subgenres", "subgenres": "all"},
    ),
    "genre-playlist-tracks (front: viewer FR, genre_only)": lambda: (
        _large_playlist("genre-playlist-tracks"),
        {"page_size": 100, "coverage": "genre_only"},
    ),
}


@pytest.mark.django_db
@pytest.mark.parametrize("scenario", SLO_MS)
def test_median_latency_within_slo(scenario, perf_record, settings):
    settings.VIEWER_CONTEXT_TOKEN = VIEWER_TOKEN
    path, params = PATHS[scenario]()
    headers = HEADERS.get(scenario, {})
    client = AppApiClient()
    for _ in range(WARMUPS):
        assert client.get(path, params, **headers).status_code == status.HTTP_200_OK

    timings = []
    for _ in range(RUNS):
        start = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = client.get(path, params, **headers)
        assert response.status_code == status.HTTP_200_OK, response.content[:500]
        timings.append((time.perf_counter() - start) * 1000)

    p50 = statistics.median(timings)
    p95 = statistics.quantiles(timings, n=20)[-1]
    print(f"\n{scenario:<38} queries={len(queries.captured_queries):>5}  p50={p50:8.1f}ms  p95={p95:8.1f}ms")
    perf_record(scenario, timings, slo_ms=SLO_MS[scenario], queries=len(queries.captured_queries))
    assert_within_slo(p50, SLO_MS[scenario])


# Cold serializes the whole ~1.7k-row tree; warm and not-modified only read the version token.
TREE_SLO_MS = {"cold": 1100, "warm": 10, "not-modified": 10}


@pytest.mark.django_db
@pytest.mark.parametrize("mode", TREE_SLO_MS)
def test_genre_tree_median_latency_within_slo(mode, perf_record):
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
    perf_record(f"genre-playlist-tree ({mode})", timings, slo_ms=TREE_SLO_MS[mode])
    assert_within_slo(p50, TREE_SLO_MS[mode])


# Reparenting a ~250-track genre under the biggest playlist's genre timed out (gunicorn 30s) before the set-based track moves.
REPARENT_SLO_MS = 1800


@pytest.mark.django_db
def test_genre_reparent_median_latency_within_slo(perf_record):
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
    perf_record("genre reparent", timings, slo_ms=REPARENT_SLO_MS)
    assert_within_slo(p50, REPARENT_SLO_MS)


# Cache cleared before each run: a cached query costs nothing, the SLO is on the projection lookup itself. Short and
# common prefixes match the most rows, the worst case for the over-fetched token tier.
SONG_SEARCH_SLO_MS = {"lo": 30, "love": 30, "the beat": 30, "nirvana smells": 20}


@pytest.mark.django_db
@pytest.mark.parametrize("query", SONG_SEARCH_SLO_MS)
def test_song_search_median_latency_within_slo(query, perf_record):
    client = AppApiClient()
    path, params = reverse("song-search"), {"q": query}

    timings = []
    for _ in range(WARMUPS + RUNS):
        cache.clear()
        start = time.perf_counter()
        response = client.get(path, params)
        timings.append((time.perf_counter() - start) * 1000)
        assert response.status_code == status.HTTP_200_OK, response.content[:500]

    p50 = statistics.median(timings[WARMUPS:])
    print(f"\nsong-search?q={query}".ljust(39) + f"results={len(response.data):>3}  p50={p50:8.1f}ms")
    perf_record(f"song-search?q={query}", timings[WARMUPS:], slo_ms=SONG_SEARCH_SLO_MS[query])
    assert_within_slo(p50, SONG_SEARCH_SLO_MS[query])


# Same method as the song search: cache cleared before each run, so the SLO is on the lookup itself. Covers a
# 2-character prefix, a word, an accent-folded form (Alté), a typo and a regional overview, across the ~6k criteria.
SEARCH_SLO_MS = {
    ("genre-search", "ro"): 40,
    ("genre-search", "jazz"): 40,
    ("genre-search", "alte"): 40,
    ("genre-search", "psychadelic rock"): 30,
    ("genre-search", "music of the andes"): 50,
    ("artist-search", "ni"): 20,
    ("artist-search", "nirvana"): 20,
    ("artist-search", "nirvanna"): 20,
}


@pytest.mark.django_db
@pytest.mark.parametrize(("route", "query"), SEARCH_SLO_MS)
def test_search_median_latency_within_slo(route, query, perf_record):
    client = AppApiClient()
    path, params = reverse(route), {"q": query}

    timings = []
    for _ in range(WARMUPS + RUNS):
        cache.clear()
        start = time.perf_counter()
        response = client.get(path, params)
        timings.append((time.perf_counter() - start) * 1000)
        assert response.status_code == status.HTTP_200_OK, response.content[:500]

    p50 = statistics.median(timings[WARMUPS:])
    print(f"\n{route}?q={query}".ljust(39) + f"results={len(response.data):>3}  p50={p50:8.1f}ms")
    perf_record(f"{route}?q={query}", timings[WARMUPS:], slo_ms=SEARCH_SLO_MS[(route, query)])
    assert_within_slo(p50, SEARCH_SLO_MS[(route, query)])


# Five stable CI self-comparisons; 3x the slowest pooled side median, rounded up.
REGION_SLO_MS = {
    "region-map-genres (identity, cold)": 280,
    "region-map-genres (identity, not-modified)": 40,
    "region-map-genres (identity, warm)": 40,
    "region-map-index (gzip, cold)": 10,
    "region-map-index (gzip, not-modified)": 10,
    "region-map-index (gzip, warm)": 10,
    "region-map-index (identity, cold)": 20,
    "region-map-index (identity, not-modified)": 10,
    "region-map-index (identity, warm)": 20,
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route", "encoding"),
    [
        ("region-map-index", "identity"),
        ("region-map-index", "gzip"),
        ("region-map-genres", "identity"),
    ],
)
@pytest.mark.parametrize("mode", ["cold", "warm", "not-modified"])
def test_region_map_median_latency_within_slo(route, encoding, mode, perf_record):
    client = AppApiClient()
    path = reverse(route)
    headers = {"HTTP_ACCEPT_ENCODING": encoding}
    initial = client.get(path, **headers)
    assert initial.status_code == status.HTTP_200_OK
    if route == "region-map-genres":
        # Coverage of the pinned index against the older pinned genre exports.
        assert len(initial.json()) == 4625
    if mode == "not-modified":
        headers["HTTP_IF_NONE_MATCH"] = initial["ETag"]
    expected_status = status.HTTP_304_NOT_MODIFIED if mode == "not-modified" else status.HTTP_200_OK
    timings = []
    query_counts = []
    try:
        for run in range(WARMUPS + RUNS):
            if mode == "cold":
                cache.clear()
            start = time.perf_counter()
            with CaptureQueriesContext(connection) as queries:
                response = client.get(path, **headers)
            elapsed = (time.perf_counter() - start) * 1000
            assert response.status_code == expected_status
            if route == "region-map-index" and expected_status == status.HTTP_200_OK:
                assert response.get("Content-Encoding", "identity") == encoding
            if run >= WARMUPS:
                timings.append(elapsed)
                query_counts.append(len(queries))
    finally:
        cache.clear()
    scenario = f"{route} ({encoding}, {mode})"
    print(f"\n{scenario}: p50={statistics.median(timings):.1f}ms queries={max(query_counts)}")
    perf_record(scenario, timings, slo_ms=REGION_SLO_MS[scenario], queries=max(query_counts))
    assert_within_slo(statistics.median(timings), REGION_SLO_MS[scenario])


# Detail ceilings require stable CI self-comparisons; these scenarios still
# participate in the same-runner relative regression gate.
@pytest.mark.django_db
@pytest.mark.parametrize("name", ["Latin", "World", "Rock", "leaf", "empty", "regional", "tag"])
@pytest.mark.parametrize("mode", ["repeated", "alternating", "cold", "post-write"])
def test_criteria_detail_latency(name, mode, perf_record):
    if name == "tag":
        criteria = Tag.objects.filter(user__isnull=True).order_by("_name").first()
        if criteria is None:
            criteria = Tag.objects.create(name="Detail benchmark", user=None)
        route = "tag-detail"
    else:
        genres = Genre.objects.filter(user__isnull=True)
        if name == "leaf":
            criteria = genres.filter(children__isnull=True, criteria_playlist__direct_songs_count__gt=0).order_by(
                "_name", "tree_name"
            )[0]
        elif name == "empty":
            criteria = genres.filter(criteria_playlist__direct_songs_count=0).order_by("_name", "tree_name")[0]
        elif name == "regional":
            criteria = genres.filter(tree_name="regional").order_by("_name")[0]
        else:
            fixture_name, tree = {
                "Latin": ("Music of Latin America", "regional"),
                "World": ("World music", "regional"),
                "Rock": ("Rock music", "canonical"),
            }[name]
            criteria = genres.get(_name=fixture_name, tree_name=tree)
        route = "genre-detail"
    path = reverse(route, kwargs={"pk": criteria.pk})
    alternate_genre = (
        Genre.objects.get(_name="World music", tree_name="regional")
        if name == "Rock"
        else Genre.objects.get(_name="Rock music", tree_name="canonical")
    )
    alternate = reverse("genre-detail", kwargs={"pk": alternate_genre.pk})
    written_song = (
        Song.objects.filter(user__isnull=True, musicbrainz_recording_id__isnull=False).order_by(
            "musicbrainz_recording_id"
        )[0]
        if mode == "post-write"
        else None
    )
    client = AppApiClient()
    timings, queries_per_run = [], []
    for run in range(WARMUPS + RUNS):
        if mode == "cold":
            cache.clear()
            _selection_index.cache_clear()
            _catalogue_projection.cache_clear()
            clear_summary_inputs_cache()
        elif mode == "alternating":
            assert client.get(alternate).status_code == status.HTTP_200_OK
        elif written_song is not None:
            target = alternate_genre if written_song.genre_id != alternate_genre.pk else None
            written_song = Song.objects.update_instance(written_song, genre=target)
        start = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = client.get(path)
        elapsed = (time.perf_counter() - start) * 1000
        assert response.status_code == status.HTTP_200_OK, response.content[:500]
        if run >= WARMUPS:
            timings.append(elapsed)
            queries_per_run.append(len(queries))
    scenario = f"criteria-detail {name} ({mode})"
    print(
        f"\n{scenario}: p50={statistics.median(timings):.1f}ms queries={max(queries_per_run)} bytes={len(response.content)}"
    )
    perf_record(scenario, timings, slo_ms=None, queries=max(queries_per_run))
