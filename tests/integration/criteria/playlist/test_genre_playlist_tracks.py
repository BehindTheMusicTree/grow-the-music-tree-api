from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_tracks_page_is_position_ordered_without_nested_playlists(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_song(title="First", genre=rock_criteria)
        second = self.model_fixture_factory.create_song(title="Second", genre=rock_criteria)
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(
            path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}), data={"page_size": 1}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["overallTotal"] == 2
        [rel] = body["results"]
        assert rel["position"] == 1
        assert rel["track"]["uuid"] == str(second.uuid)
        assert "playlists" not in rel["track"]

    def test_tracks_page_returns_track_youtube_video_id(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_song(title="Track Title", genre=rock_criteria, youtube_video_id="abc123defgh")
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["track"]["youtubeVideoId"] == "abc123defgh"

    def test_tracks_page_nests_youtube_video_and_skips_unplayable(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_song(title="Track Title", genre=rock_criteria, youtube_video_id="abc123defgh")
        self.model_fixture_factory.create_song(title="No video", genre=rock_criteria, youtube_video_id=None)
        self.model_fixture_factory.create_song(
            title="Private", genre=rock_criteria, youtube_video_id="zzz123defgh", youtube_unplayable_reason="private"
        )
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}))

        [rel] = response.json()["results"]
        assert rel["track"]["youtubeVideo"] == {
            "id": "abc123defgh",
            "unplayableReason": None,
            "viewCount": None,
            "availability": {"status": "unknown", "reason": None, "country": None},
        }

    def test_tracks_from_starts_at_given_track_404s_on_absent_and_400s_on_non_uuid(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        for title in ("A", "B", "C"):
            self.model_fixture_factory.create_song(title=title, genre=rock_criteria)
        jazz_track = self.model_fixture_factory.create_song(
            title="Elsewhere", genre=self.model_fixture_factory.create_genre(name="jazz")
        )
        path = reverse("genre-playlist-tracks", kwargs={"pk": GenrePlaylist.objects.get(criteria=rock_criteria).uuid})
        full_order = [rel["track"]["uuid"] for rel in self.api_client.get(path=path).json()["results"]]

        response = self.api_client.get(path=path, data={"from": full_order[1]})

        assert response.status_code == status.HTTP_200_OK
        assert [rel["track"]["uuid"] for rel in response.json()["results"]] == full_order[1:]
        assert response.json()["overallTotal"] == 2
        assert self.api_client.get(path=path, data={"from": str(jazz_track.uuid)}).status_code == (
            status.HTTP_404_NOT_FOUND
        )
        assert self.api_client.get(path=path, data={"from": "nope"}).status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(VIEWER_CONTEXT_TOKEN="trusted")
    def test_country_filter_precedes_pagination_and_anchor_without_changing_membership(self):
        genre = self.model_fixture_factory.create_genre(name="regional")
        first = self.model_fixture_factory.create_song(title="First", genre=genre)
        blocked = self.model_fixture_factory.create_song(title="Blocked", genre=genre)
        blocked.youtube_region_restriction = {"mode": "allowed", "countries": ["FR"]}
        blocked.save(update_fields=["youtube_region_restriction"])
        playlist = GenrePlaylist.objects.get(criteria=genre)
        path = reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid})
        headers = {"HTTP_X_VIEWER_CONTEXT_TOKEN": "trusted", "HTTP_X_VIEWER_COUNTRY": "AL"}
        response = self.api_client.get(path, {"page_size": 1}, **headers)
        assert response.status_code == 200
        assert response.json()["overallTotal"] == 1
        assert response.json()["results"][0]["track"]["uuid"] == str(first.uuid)
        assert response.json()["results"][0]["track"]["youtubeVideo"]["availability"]["country"] == "AL"
        assert response["Cache-Control"] == "private, no-store"
        assert self.api_client.get(path, {"from": str(blocked.uuid)}, **headers).status_code == 404
        assert (
            self.api_client.get(path, HTTP_X_VIEWER_CONTEXT_TOKEN="trusted", HTTP_X_VIEWER_COUNTRY="FR").json()[
                "overallTotal"
            ]
            == 2
        )
        playlist.refresh_from_db()
        assert playlist.tracks_count == 2
