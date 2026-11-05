from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle

from grow.model.album.Album import Album
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.song.Song import Song
from grow.model.song_search.SongSearch import SongSearch
from grow.model.song_search.SongSearchState import SongSearchState
from grow.serializer.model.song.search import SEARCH_LIMIT_MAX
from grow.song_search.rebuild import rebuild_song_search
from tests.utils.AppTestCase import AppTestCase


class TestSongSearchValidation(AppTestCase):
    def setUp(self):
        super().setUp()
        self.api_client.credentials()

    def search(self, **params):
        return self.api_client.get(path=reverse("song-search"), data=params)

    def test_query_too_short_or_long_then_400(self):
        assert self.search(q="a").status_code == status.HTTP_400_BAD_REQUEST
        assert self.search(q="a" * 101).status_code == status.HTTP_400_BAD_REQUEST
        assert self.search().status_code == status.HTTP_400_BAD_REQUEST

    def test_limit_and_filters_validated(self):
        assert self.search(q="numb", limit=SEARCH_LIMIT_MAX + 1).status_code == status.HTTP_400_BAD_REQUEST
        assert self.search(q="numb", limit=0).status_code == status.HTTP_400_BAD_REQUEST
        assert self.search(q="numb", genre="maybe").status_code == status.HTTP_400_BAD_REQUEST
        assert self.search(q="numb", playable="sometimes").status_code == status.HTTP_400_BAD_REQUEST

    def test_throttled_per_client(self):
        cache.clear()
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"song-search": "2/min"}):
            codes = [self.search(q="a").status_code for _ in range(3)]

        assert codes == [status.HTTP_400_BAD_REQUEST, status.HTTP_400_BAD_REQUEST, status.HTTP_429_TOO_MANY_REQUESTS]


@pytest.mark.postgres
class TestSongSearch(AppTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.api_client.credentials()
        self.factory = self.model_fixture_factory
        self.rock = self.factory.create_genre("Rock")

    def song(self, title: str, *artists: str, genre=..., **kwargs) -> Song:
        song = self.factory.create_song(title, self.rock if genre is ... else genre, **kwargs)
        for name in artists:
            song.artists.add(self.factory.create_artist(name))
        return song

    def search(self, q: str, **params):
        return self.api_client.get(path=reverse("song-search"), data={"q": q, **params})

    def titles(self, q: str, **params) -> list[str]:
        response = self.search(q, **params)
        assert response.status_code == status.HTTP_200_OK, response.content
        return [item["title"] for item in response.data]

    def test_not_rebuilt_yet_then_503(self):
        self.song("Comfortably Numb", "Pink Floyd")

        response = self.search("numb")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["details"]["code"] == "search_unavailable"

    def test_anonymous_search_then_result_shape(self):
        song = self.song("Comfortably Numb", "Pink Floyd", first_release_year=1979)
        rebuild_song_search()

        (item,) = self.search("numb").json()

        artist = song.artists.get()
        assert item == {
            "uuid": str(song.uuid),
            "title": "Comfortably Numb",
            "artists": [{"uuid": str(artist.uuid), "name": "Pink Floyd", "isSpecialPurpose": False}],
            "genre": {"uuid": str(self.rock.uuid), "name": "Rock"},
            "youtubeVideo": {"id": "dQw4w9WgXcQ", "unplayableReason": None, "viewCount": None},
            "firstReleaseYear": 1979,
        }

    def test_invalid_bearer_token_is_ignored(self):
        self.song("Comfortably Numb")
        rebuild_song_search()
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-grow-token")

        assert self.search("numb").status_code == status.HTTP_200_OK

    def test_accent_case_and_punctuation_folded(self):
        self.song("Jóga", "Björk")
        self.song("Back in Black", "AC/DC")
        self.song("Paper Planes", "M.I.A.")
        rebuild_song_search()

        assert self.titles("JOGA") == ["Jóga"]
        assert self.titles("bjork") == ["Jóga"]
        assert self.titles("ac/dc") == self.titles("ac dc") == ["Back in Black"]
        assert self.titles("m.i.a paper") == ["Paper Planes"]

    def test_every_word_as_a_prefix_in_any_order(self):
        self.song("Bohemian Rhapsody", "Queen")
        self.song("Bohemian Like You", "The Dandy Warhols")
        rebuild_song_search()

        assert self.titles("queen bohem") == self.titles("bohemian que") == ["Bohemian Rhapsody"]
        assert self.titles("rhapsody dandy") == []

    def test_exact_title_before_title_prefix_before_rank(self):
        # The artist match is popular and playable, the title matches are not: the tiers still win.
        self.song("Numb Remix", genre=None, youtube_video_id=None)
        self.song("Numb", genre=None, youtube_video_id=None)
        self.song("Comfortably Numb", recording_count=200, youtube_view_count=10**9)
        rebuild_song_search()

        assert self.titles("numb") == ["Numb", "Numb Remix", "Comfortably Numb"]

    def test_title_prefix_kept_past_many_more_popular_word_matches(self):
        for i in range(9):
            self.song(f"Hit {i}", "Love Band", recording_count=200, youtube_view_count=10**9)
        self.song("Lovesick", genre=None, youtube_video_id=None)
        rebuild_song_search()

        assert self.titles("love", limit=2)[0] == "Lovesick"

    def test_rank_puts_genre_then_playable_first(self):
        self.song("Lithium Genreless", genre=None)
        self.song("Lithium Unplayable", youtube_video_id=None)
        self.song("Lithium Both")
        self.song("Lithium Neither", genre=None, youtube_video_id=None)
        rebuild_song_search()

        assert self.titles("lithium") == [
            "Lithium Both",
            "Lithium Unplayable",
            "Lithium Genreless",
            "Lithium Neither",
        ]

    def test_artist_name_alone_finds_their_songs_by_popularity(self):
        self.song("Lithium", "Nirvana", youtube_view_count=10)
        self.song("Smells Like Teen Spirit", "Nirvana", youtube_view_count=10**8)
        rebuild_song_search()

        assert self.titles("nirvana") == ["Smells Like Teen Spirit", "Lithium"]

    def test_genre_and_playable_filters_and_genreless_results(self):
        self.song("Heart Genre")
        self.song("Heart Genreless", genre=None)
        self.song("Heart Unplayable", youtube_video_id=None)
        rebuild_song_search()

        assert self.titles("heart", genre="without") == ["Heart Genreless"]
        assert self.titles("heart", genre="with") == ["Heart Genre", "Heart Unplayable"]
        assert self.titles("heart", playable="false") == ["Heart Unplayable"]
        assert self.titles("heart", genre="with", playable="true") == ["Heart Genre"]
        (genreless,) = self.search("heart genreless").json()
        assert genreless["genre"] is None

    def test_limit(self):
        for i in range(5):
            self.song(f"Song {i}")
        rebuild_song_search()

        assert len(self.titles("song", limit=3)) == 3

    def test_punctuation_only_query_then_empty(self):
        self.song("Comfortably Numb")
        rebuild_song_search()

        assert self.titles("?!") == []

    def test_query_budget(self):
        for i in range(3):
            self.song(f"Song {i}", f"Artist {i}")
        rebuild_song_search()

        with CaptureQueriesContext(connection) as queries:
            assert len(self.titles("song")) == 3
        # SAVEPOINT/RELEASE of the read transaction excluded: ready+fold, search, songs, artists.
        assert len([q for q in queries if "SAVEPOINT" not in q["sql"]]) == 4

    def test_cached_until_a_song_write(self):
        song = self.song("Comfortably Numb")
        rebuild_song_search()
        assert self.titles("numb") == ["Comfortably Numb"]

        with CaptureQueriesContext(connection) as queries:
            assert self.titles("numb") == ["Comfortably Numb"]
        assert not queries.captured_queries

        with self.captureOnCommitCallbacks(execute=True):
            Song.objects.update_instance(song, title="Numb")
        assert self.titles("numb") == ["Numb"]

    def test_cached_until_a_song_delete(self):
        album = self.factory.create_album("Meteora")
        self.song("Numb Album Cut", album=album)
        song = self.song("Numb")
        rebuild_song_search()
        assert self.titles("numb") == ["Numb", "Numb Album Cut"]

        with self.captureOnCommitCallbacks(execute=True):
            Song.objects.delete_instance(song)
        assert self.titles("numb") == ["Numb Album Cut"]

        with self.captureOnCommitCallbacks(execute=True):
            Album.objects.delete_instance(album)
        assert self.titles("numb") == []

    def test_orm_writes_keep_projection_in_sync(self):
        song = self.song("Comfortably Numb", "Pink Floyd")
        rebuild_song_search()
        created = self.song("Lithium")

        Song.objects.update_instance(song, youtube_video_id=None, genre=None)

        assert SongSearch.objects.filter(pk=created.pk).exists()
        assert SongSearch.objects.get(pk=song.pk).playable is False
        assert SongSearch.objects.drift() == {"missing": 0, "orphaned": 0, "stale": 0}
        song.delete()
        assert not SongSearch.objects.filter(pk=song.pk).exists()

    def test_deleting_a_root_genre_makes_its_songs_genreless_in_the_projection(self):
        grunge = self.factory.create_genre("Grunge")
        song = self.song("Lithium", genre=grunge)
        rebuild_song_search()

        Genre.objects.delete_instance(grunge)

        assert SongSearch.objects.get(pk=song.pk).has_genre is False
        assert SongSearch.objects.drift() == {"missing": 0, "orphaned": 0, "stale": 0}

    def test_rebuild_swaps_table_keeping_indexes_and_marks_ready(self):
        self.song("Comfortably Numb")
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'grow_song_search' ORDER BY indexname")
            before = cursor.fetchall()

        assert rebuild_song_search() == 1
        assert rebuild_song_search() == 1

        with connection.cursor() as cursor:
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'grow_song_search' ORDER BY indexname")
            assert cursor.fetchall() == before
        state = SongSearchState.load()
        assert state.ready and state.rebuilt_on is not None
        assert SongSearch.objects.drift() == {"missing": 0, "orphaned": 0, "stale": 0}

    def test_check_command_reports_drift(self):
        song = self.song("Comfortably Numb")
        call_command("rebuild_song_search")
        call_command("rebuild_song_search", "--check")

        with connection.cursor() as cursor:
            cursor.execute("UPDATE grow_song_search SET rank_score = -1 WHERE track_id = %s", [song.pk])
        with pytest.raises(CommandError):
            call_command("rebuild_song_search", "--check")
