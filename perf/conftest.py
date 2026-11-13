import gzip
import json
import os
import time
from pathlib import Path

import pytest
from django.conf import settings
from django.db import connection
from django.db.models import Count
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide
from the_music_tree_genre_kit.criteria.track_playlist_rel.Fields import Fields as TrackPlaylistRelFields
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.artist.bulk_import.merge import WRITTEN_MODELS as ARTIST_MERGE_MODELS
from grow.bulk_import.analyze import tables
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song_search.SongSearchState import SongSearchState
from grow.song_search.rebuild import rebuild_song_search
from grow.track.bulk_import.merge import WRITTEN_MODELS as SONG_MERGE_MODELS
from grow.view.viewset.model.criteria.children.genre.GenreViewSet import TREE_IMPORT_MODELS
from perf.region_fixture import seed_region_snapshot
from tests.utils.AppApiClient import AppApiClient
from tests.utils.curation_export import export_curation

# Prod Gold exports from the-music-tree-pipelines, pinned so SLOs are measured against fixed data. Refresh: README.
FIXTURES = Path(__file__).parent / "fixtures"
TREES = ["1_canonical_genre_tree.json.gz", "1_regional_genre_tree.json.gz"]
SONGS = "2_songs.json.gz"


def _timed(label: str, request):
    start = time.perf_counter()
    response = request()
    assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED, status.HTTP_202_ACCEPTED), (
        response.content[:500]
    )
    print(f"\nimport {label:<38} {(time.perf_counter() - start) * 1000:8.0f}ms")
    return response


def _seed() -> None:
    # Same order, auth and protocol as the nightly sync: songs resolve their genre against the imported trees.
    client = AppApiClient()
    client.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)
    exported_on = export_curation(client)
    trees = []
    for fixture in TREES:
        with gzip.open(FIXTURES / fixture) as file:
            trees.append({**json.load(file), "curationExportedOn": exported_on})
    body = {"trees": trees}
    started = _timed(
        "genre trees (queue+merge)", lambda: client.post(reverse("genre-list") + "trees/import-runs/", body)
    )
    task_id = started.json()["taskId"]
    status_url = reverse("genre-list") + f"trees/import/{task_id}/status/"
    start = time.perf_counter()
    while (polled := client.get(status_url).json())["status"] not in ("success", "failure"):
        assert time.perf_counter() - start < 1800, polled
        time.sleep(1)
    assert polled["status"] == "success", polled
    print(f"\nimport {'genre trees (merge)':<38} {(time.perf_counter() - start) * 1000:8.0f}ms")
    with gzip.open(FIXTURES / SONGS) as file:
        part = gzip.compress(
            "".join(json.dumps({"first_release_year": None, **song}) + "\n" for song in json.load(file)).encode()
        )
    runs = reverse("song-list") + "songs/import-runs/"
    run_id = client.post(runs).data["run_id"]
    _timed(
        f"{SONGS} (part)",
        lambda: client.put(
            f"{runs}{run_id}/parts/0/",
            part,
            format=None,
            content_type="application/x-ndjson",
            HTTP_CONTENT_ENCODING="gzip",
        ),
    )
    _timed(f"{SONGS} (commit)", lambda: client.post(f"{runs}{run_id}/commit/"))


def largest_genre_playlist() -> GenrePlaylist:
    rels = TrackPlaylistRel._default_manager.filter(
        **{f"{TrackPlaylistRelFields.PLAYLIST}__in": GenrePlaylist.objects.values("pk")}
    )
    counts = rels.values(TrackPlaylistRelFields.PLAYLIST).annotate(tracks=Count("pk")).order_by("-tracks")
    return GenrePlaylist.objects.get(pk=counts[0][TrackPlaylistRelFields.PLAYLIST])


def mid_size_genre(*, exclude: Genre) -> Genre:
    rels = TrackPlaylistRel._default_manager.filter(
        **{f"{TrackPlaylistRelFields.PLAYLIST}__in": GenrePlaylist.objects.exclude(criteria=exclude).values("pk")}
    )
    counts = rels.values(TrackPlaylistRelFields.PLAYLIST).annotate(tracks=Count("pk")).filter(tracks__gte=200)
    # A pop-side genre can't move under a root that already has a pop child, which would make the move invalid.
    playlist = (
        GenrePlaylist.objects.filter(
            pk__in=[row[TrackPlaylistRelFields.PLAYLIST] for row in counts], criteria__parent__isnull=False
        )
        .exclude(criteria__genre__side=CriteriaSide.POP)
        .order_by("criteria__name", "pk")[0]
    )
    return playlist.criteria


def _assert_imports_analyzed() -> None:
    """
    Fails when an import left a filled table without planner statistics. Rounds would then measure plans picked on
    pre-import row counts until autoanalyze catches up (round 1 at 6x round 2 on one scenario), not the code.
    """
    unanalyzed = []
    with connection.cursor() as cursor:
        for table in tables((*TREE_IMPORT_MODELS, *SONG_MERGE_MODELS, *ARTIST_MERGE_MODELS)):
            cursor.execute(
                f"SELECT EXISTS (SELECT 1 FROM {table}) AND NOT EXISTS ("
                "SELECT 1 FROM pg_stats WHERE schemaname = current_schema() AND tablename = %s)",
                [table],
            )
            if cursor.fetchone()[0]:
                unanalyzed.append(table)
    if unanalyzed:
        raise RuntimeError(f"seeded tables without planner statistics: {', '.join(unanalyzed)}")


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        if not Genre.objects.exists():  # --reuse-db keeps the seed across runs
            _seed()
            _assert_imports_analyzed()
        seed_region_snapshot()
        # Checked apart from the seed: a database reused from before song search existed still needs its first build.
        if not SongSearchState.load().ready:
            start = time.perf_counter()
            rows = rebuild_song_search()
            label = f"song search rebuild ({rows} songs)"
            print(f"\nimport {label:<38} {(time.perf_counter() - start) * 1000:8.0f}ms")


# Machine-readable results for perf/compare.py: written when PERF_RESULTS names the output file.
_results: dict[str, dict] = {}


def _slo_assert_enabled() -> bool:
    # The A/B gate turns per-run asserts off and judges the SLO on the pooled median of every run instead.
    value = os.environ.get("PERF_SLO_ASSERT", "1")
    if value not in ("0", "1"):
        raise ValueError(f"PERF_SLO_ASSERT must be 0 or 1, got {value!r}")
    return value == "1"


@pytest.fixture(scope="session")
def perf_record():
    def record(scenario: str, timings_ms: list[float], *, slo_ms: float | None, queries: int | None = None) -> None:
        if scenario in _results:
            raise ValueError(f"perf scenario recorded twice: {scenario}")
        _results[scenario] = {"timings_ms": timings_ms, "slo_ms": slo_ms, "queries": queries}

    return record


def assert_within_slo(p50: float, slo_ms: float) -> None:
    if _slo_assert_enabled():
        assert p50 <= slo_ms


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("PERF_RESULTS")
    if path:
        Path(path).write_text(json.dumps({"version": 1, "scenarios": _results}, indent=2, sort_keys=True))
