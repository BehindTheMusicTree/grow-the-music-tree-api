from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    list_endpoint = "recording-list"

    def test_list_returns_created_tracks(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        recording = self.model_fixture_factory.create_recording(
            title="Mine", genre=genre, youtube_video_id="abc123defgh"
        )

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["overallTotal"] == 1
        assert response.data["results"][0]["uuid"] == str(recording.uuid)

    def test_list_does_not_return_other_users_tracks(self):
        other_user = User.objects.create(username="other-user")
        other_genre = self.model_fixture_factory.create_genre("Jazz", user=other_user)
        self.model_fixture_factory.create_recording(
            title="Not Mine", genre=other_genre, user=other_user, youtube_video_id="def456ghijk"
        )

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["overallTotal"] == 0

    def test_list_includes_youtube_video_id(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_recording(title="Track Title", genre=genre, youtube_video_id="abc123defgh")

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.data["results"][0]["youtube_video_id"] == "abc123defgh"

    def test_list_includes_musicbrainz_recording_id(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_recording(
            title="Track Title", genre=genre, musicbrainz_recording_id="b1a9c0e9-d987-4042-ae91-78d6a3267d69"
        )

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.data["results"][0]["musicbrainz_recording_id"] == "b1a9c0e9-d987-4042-ae91-78d6a3267d69"

    def test_list_includes_null_youtube_unplayable_reason_for_playable_track(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_recording(title="Track Title", genre=genre)

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.json()["results"][0]["youtubeUnplayableReason"] is None

    def test_list_includes_recording_without_video_with_null_youtube_video(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_recording(title="No video", genre=genre, youtube_video_id=None)

        response = self.api_client.get(path=reverse(self.list_endpoint))

        [recording] = response.json()["results"]
        assert recording["youtubeVideo"] is None

    def test_list_nests_youtube_video(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_recording(title="Track Title", genre=genre, youtube_video_id="abc123defgh")

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.json()["results"][0]["youtubeVideo"] == {"id": "abc123defgh", "unplayableReason": None}

    def test_legacy_youtube_route_still_lists_recordings(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        recording = self.model_fixture_factory.create_recording(title="Mine", genre=genre)

        response = self.api_client.get(path=reverse("youtube-track-list"))

        assert response.status_code == status.HTTP_200_OK
        assert [r["uuid"] for r in response.json()["results"]] == [str(recording.uuid)]
