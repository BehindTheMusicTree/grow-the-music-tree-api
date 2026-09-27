from collections.abc import Callable

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppApiClient import AppApiClient
from tests.utils.ModelFixtureFactory import ModelFixtureFactory

# Queries per request, whatever the number of rows or tracks. Raising one is a reviewed decision, not a fix.
BUDGETS = {
    "genre-playlist-list": 4,
    "tag-playlist-list": 4,
    "playlist-list": 2,
    "genre-list": 4,
    "tag-list": 4,
    "genre-playlist-detail": 6,
    "playlist-detail": 6,
}

factory = ModelFixtureFactory(default_user=None)


def _seed_genres(start: int, stop: int) -> None:
    root = GenrePlaylist.objects.get(criteria__name="Root").criteria if start else factory.create_genre("Root")
    for index in range(start, stop):
        genre = factory.create_genre(f"Genre {index}", parent=root)
        factory.create_tag(f"Tag {index}")
        factory.create_youtube_track(title=f"Track {index}", genre=genre)


def _seed_tracks(start: int, stop: int) -> None:
    genre = GenrePlaylist.objects.get(criteria__name="Root").criteria if start else factory.create_genre("Root")
    for index in range(start, stop):
        factory.create_youtube_track(title=f"Track {index}", genre=genre)


def _root_playlist_path(name: str) -> str:
    return reverse(name, kwargs={"pk": GenrePlaylist.objects.get(criteria__name="Root").uuid})


LIST_PATH = {"page_size": 100}
SCENARIOS: dict[str, tuple[Callable[[int, int], None], Callable[[], str]]] = {
    "genre-playlist-list": (_seed_genres, lambda: reverse("genre-playlist-list")),
    "tag-playlist-list": (_seed_genres, lambda: reverse("tag-playlist-list")),
    "playlist-list": (_seed_genres, lambda: reverse("playlist-list")),
    "genre-list": (_seed_genres, lambda: reverse("genre-list")),
    "tag-list": (_seed_genres, lambda: reverse("tag-list")),
    "genre-playlist-detail": (_seed_tracks, lambda: _root_playlist_path("genre-playlist-detail")),
    "playlist-detail": (_seed_tracks, lambda: _root_playlist_path("playlist-detail")),
}


def _count_queries(path: str) -> int:
    with CaptureQueriesContext(connection) as queries:
        response = AppApiClient().get(path, LIST_PATH)
    assert response.status_code == status.HTTP_200_OK
    return len(queries.captured_queries)


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", BUDGETS)
def test_query_count_is_constant_and_within_budget(endpoint):
    seed, path = SCENARIOS[endpoint]
    seed(0, 2)
    few_rows = _count_queries(path())
    seed(2, 12)
    many_rows = _count_queries(path())

    assert (few_rows, many_rows) == (many_rows, many_rows), f"{endpoint} issues queries per row"
    assert many_rows <= BUDGETS[endpoint]
