from django.urls import reverse
from rest_framework import status

from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_import_creates_tracks_from_payload(self):
        self.model_fixture_factory.create_genre("Rock")
        payload = [
            {
                "title": "Comfortably Numb",
                "artist": "Pink Floyd",
                "youtube_video_id": "abc123defgh",
                "genre_name": "Rock",
            }
        ]

        response = self.api_client.post(path=reverse("youtube-track-list") + "songs/import/", data=payload)

        assert response.status_code == status.HTTP_201_CREATED
        titles = set(YoutubeTrack.objects.filter(user=self.system_user).values_list("title", flat=True))
        assert titles == {"Comfortably Numb"}

    def test_import_rejects_invalid_payload(self):
        response = self.api_client.post(
            path=reverse("youtube-track-list") + "songs/import/", data=[{"title": "Missing"}]
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
