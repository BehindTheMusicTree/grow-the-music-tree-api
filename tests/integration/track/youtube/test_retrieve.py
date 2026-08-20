import uuid

from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_retrieve_returns_detailed_representation(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        artist = self.model_fixture_factory.create_artist("Pink Floyd")
        album = self.model_fixture_factory.create_album("The Wall")
        youtube_track = self.model_fixture_factory.create_youtube_track(
            title="Track Title",
            genre=genre,
            artists=[artist],
            album=album,
            youtube_video_id="abc123defgh",
        )

        response = self.api_client.get(path=reverse("youtube-track-detail", kwargs={"pk": youtube_track.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["uuid"] == str(youtube_track.uuid)
        assert response.data["title"] == "Track Title"
        assert response.data["youtube_video_id"] == "abc123defgh"
        assert response.data["relative_url"] == youtube_track.relative_url
        assert response.data["artists"][0]["name"] == "Pink Floyd"
        assert response.data["album"]["name"] == "The Wall"
        assert response.data["genre"]["name"] == "Rock"

    def test_retrieve_with_unknown_uuid_then_404_not_found(self):
        response = self.api_client.get(path=reverse("youtube-track-detail", kwargs={"pk": uuid.uuid4()}))

        assert response.status_code == status.HTTP_404_NOT_FOUND
