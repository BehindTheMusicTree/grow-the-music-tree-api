from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    list_endpoint = "youtube-track-list"

    def test_list_returns_created_tracks(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        youtube_track = self.model_fixture_factory.create_youtube_track(title="Mine", genre=genre)

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["overallTotal"] == 1
        assert response.data["results"][0]["uuid"] == str(youtube_track.uuid)

    def test_list_does_not_return_other_users_tracks(self):
        other_user = User.objects.create(username="other-user")
        other_genre = self.model_fixture_factory.create_genre("Jazz", user=other_user)
        self.model_fixture_factory.create_youtube_track(title="Not Mine", genre=other_genre, user=other_user)

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["overallTotal"] == 0

    def test_list_includes_youtube_video_id(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_youtube_track(
            title="Track Title", genre=genre, youtube_video_id="abc123defgh"
        )

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.data["results"][0]["youtube_video_id"] == "abc123defgh"
