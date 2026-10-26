import uuid

from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_retrieve_returns_detailed_representation(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        artist = self.model_fixture_factory.create_artist("Pink Floyd")
        album = self.model_fixture_factory.create_album("The Wall")
        song = self.model_fixture_factory.create_song(
            title="Track Title",
            genre=genre,
            artists=[artist],
            album=album,
            youtube_video_id="abc123defgh",
            musicbrainz_recording_id="b1a9c0e9-d987-4042-ae91-78d6a3267d69",
        )

        response = self.api_client.get(path=reverse("song-detail", kwargs={"pk": song.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["uuid"] == str(song.uuid)
        assert response.data["title"] == "Track Title"
        assert response.data["youtube_video_id"] == "abc123defgh"
        assert response.data["musicbrainz_recording_id"] == "b1a9c0e9-d987-4042-ae91-78d6a3267d69"
        assert response.data["relative_url"] == song.relative_url
        assert response.data["artists"][0]["name"] == "Pink Floyd"
        assert response.data["album"]["name"] == "The Wall"
        assert response.data["genre"]["name"] == "Rock"

    def test_retrieve_with_unknown_uuid_then_404_not_found(self):
        response = self.api_client.get(path=reverse("song-detail", kwargs={"pk": uuid.uuid4()}))

        assert response.status_code == status.HTTP_404_NOT_FOUND
