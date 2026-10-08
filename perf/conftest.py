import gzip
import json
import time
from pathlib import Path

import pytest
from django.conf import settings
from django.db.models import Count
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.track_playlist_rel.Fields import Fields as TrackPlaylistRelFields
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppApiClient import AppApiClient

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
    for fixture in TREES:
        with gzip.open(FIXTURES / fixture) as file:
            payload = json.load(file)
        _timed(fixture, lambda payload=payload: client.post(reverse("genre-list") + "tree/import/", payload))
    with gzip.open(FIXTURES / SONGS) as file:
        part = gzip.compress("".join(json.dumps(song) + "\n" for song in json.load(file)).encode())
    runs = reverse("youtube-track-list") + "songs/import-runs/"
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


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        if not Genre.objects.exists():  # --reuse-db keeps the seed across runs
            _seed()
