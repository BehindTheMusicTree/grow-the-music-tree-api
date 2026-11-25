import base64
import json
from uuid import uuid4

from django.urls import reverse
from rest_framework import status

from grow.model.artist_song.ArtistSong import ArtistSong
from grow.model.artist_song.ArtistSongState import ArtistSongState
from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase
from tests.utils.song_graph import install_song_graph


class TestCase(AppTestCase):
    list_endpoint = "song-list"

    def _artist_with_songs(self, rows):
        """rows: (title, album_year). The projection is Postgres-maintained, so the rows are written directly."""
        genre = self.model_fixture_factory.create_genre("Rock")
        artist = self.model_fixture_factory.create_artist("Handel")
        songs = []
        for title, year in rows:
            song = self.model_fixture_factory.create_song(title=title, genre=genre)
            song.artists.add(artist)
            ArtistSong.objects.create(artist=artist, song=song, title=title, album_year=year)
            songs.append(song)
        install_song_graph({genre: songs})
        return artist, songs

    def _walk(self, artist, ordering, size=2):
        response = self.api_client.get(
            path=reverse(self.list_endpoint), data={"artist": str(artist.uuid), "ordering": ordering, "pageSize": size}
        )
        seen = []
        while True:
            assert response.status_code == status.HTTP_200_OK, response.content
            assert response.data["overallTotal"] is None
            seen += [r["title"] for r in response.data["results"]]
            if response.data["next"] is None:
                return seen
            response = self.api_client.get(response.data["next"])

    def test_not_ready_is_503(self):
        artist, _ = self._artist_with_songs([("A", 2000)])

        response = self.api_client.get(path=reverse(self.list_endpoint), data={"artist": str(artist.uuid)})

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_title_cursor_walks_every_song_once_in_order(self):
        artist, _ = self._artist_with_songs([(t, 2000) for t in ("d", "a", "c", "b", "e")])
        ArtistSongState.objects.update_or_create(pk=1, defaults={"ready": True})

        assert self._walk(artist, "title") == ["a", "b", "c", "d", "e"]

    def test_title_cursor_keeps_tied_titles(self):
        artist, _ = self._artist_with_songs([("same", None)] * 5)
        ArtistSongState.objects.update_or_create(pk=1, defaults={"ready": True})

        assert self._walk(artist, "title") == ["same"] * 5

    def test_year_cursor_orders_descending_with_undated_last(self):
        artist, _ = self._artist_with_songs(
            [("n1", None), ("y1990", 1990), ("y2010", 2010), ("n2", None), ("y1990b", 1990), ("y2000", 2000)]
        )
        ArtistSongState.objects.update_or_create(pk=1, defaults={"ready": True})

        seen = self._walk(artist, "-albumYear", size=2)

        assert len(seen) == 6
        assert seen[0] == "y2010"
        assert seen[1] == "y2000"
        assert set(seen[2:4]) == {"y1990", "y1990b"}
        assert set(seen[4:]) == {"n1", "n2"}

    def test_unsupported_ordering_and_filters_are_rejected(self):
        ArtistSongState.objects.update_or_create(pk=1, defaults={"ready": True})
        for extra in (
            {"ordering": "-title"},
            {"playable": "true"},
            {"genre": str(uuid4())},
            {"page": 1, "cursor": "invalid"},
            {"page": 1, "unknown": "true"},
        ):
            response = self.api_client.get(path=reverse(self.list_endpoint), data={"artist": str(uuid4()), **extra})
            assert response.status_code == status.HTTP_400_BAD_REQUEST, extra

    def test_explicit_page_keeps_numbered_pagination_and_count(self):
        artist, _ = self._artist_with_songs([("B", 2000), ("A", 2000)])
        response = self.api_client.get(
            path=reverse(self.list_endpoint),
            data={"artist": str(artist.uuid), "ordering": "title", "page": 1, "page_size": 1},
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["overallTotal"] == response.data["totalPages"] == 2
        assert response.data["page"] == 1
        assert [song["title"] for song in response.data["results"]] == ["A"]

        second = self.api_client.get(response.data["next"])
        assert second.data["page"] == 2
        assert [song["title"] for song in second.data["results"]] == ["B"]
        previous = self.api_client.get(second.data["previous"])
        assert previous.data["page"] == 1

    def test_numbered_playback_honors_genre_and_start_song(self):
        artist, songs = self._artist_with_songs([("A", 2000), ("B", 2000), ("C", 2000), ("D", 2000)])
        other_genre = self.model_fixture_factory.create_genre("Jazz")
        Song.objects.filter(pk=songs[2].pk).update(youtube_video_id=None)
        install_song_graph({songs[0].genre: songs[:3], other_genre: [songs[3]]})
        response = self.api_client.get(
            path=reverse(self.list_endpoint),
            data={
                "artist": str(artist.uuid),
                "ordering": "title",
                "page": 1,
                "playable": "true",
                "genre": str(songs[0].genre.uuid),
                "from": str(songs[1].uuid),
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["overallTotal"] == 1
        assert [song["title"] for song in response.data["results"]] == ["B"]

    def test_genre_panel_honors_artist_through_uuid_cursor_pages(self):
        artist, songs = self._artist_with_songs([("A", 2000), ("B", 2000), ("C", 2000)])
        songs[2].artists.remove(artist)
        response = self.api_client.get(
            path=reverse(self.list_endpoint),
            data={
                "artist": str(artist.uuid),
                "genre": str(songs[0].genre.uuid),
                "with_total": "false",
                "page_size": 1,
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["page"] is None
        assert len(response.data["results"]) == 1

        second = self.api_client.get(response.data["next"])
        assert second.status_code == status.HTTP_200_OK, second.content
        assert second.data["next"] is None
        assert {item["title"] for item in response.data["results"] + second.data["results"]} == {"A", "B"}

    def test_invalid_cursor_is_rejected(self):
        ArtistSongState.objects.update_or_create(pk=1, defaults={"ready": True})

        response = self.api_client.get(
            path=reverse(self.list_endpoint), data={"artist": str(uuid4()), "cursor": "not-a-cursor"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_forged_cursors_are_rejected(self):
        ArtistSongState.objects.update_or_create(pk=1, defaults={"ready": True})
        for payload in (["x", 5], ["x", [1]], ["\x00", str(uuid4())]):
            cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

            response = self.api_client.get(
                path=reverse(self.list_endpoint), data={"artist": str(uuid4()), "cursor": cursor}
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST, payload
