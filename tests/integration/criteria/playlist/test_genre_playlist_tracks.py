from django.urls import reverse
from rest_framework import status

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_tracks_page_is_position_ordered_without_nested_playlists(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_youtube_track(title="First", genre=rock_criteria)
        second = self.model_fixture_factory.create_youtube_track(title="Second", genre=rock_criteria)
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
        self.model_fixture_factory.create_youtube_track(
            title="Track Title", genre=rock_criteria, youtube_video_id="abc123defgh"
        )
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["track"]["youtubeVideoId"] == "abc123defgh"

    def test_tracks_page_returns_track_youtube_unplayable_reason(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_youtube_track(
            title="Track Title", genre=rock_criteria, youtube_unplayable_reason="not_embeddable"
        )
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["track"]["youtubeUnplayableReason"] == "not_embeddable"
