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

        assert response.status_code == status.HTTP_202_ACCEPTED
        task_id = response.data["task_id"]
        titles = set(YoutubeTrack.objects.filter(user=self.system_user).values_list("title", flat=True))
        assert titles == {"Comfortably Numb"}

        status_response = self.api_client.get(path=reverse("youtube-track-list") + f"songs/import/{task_id}/status/")
        assert status_response.status_code == status.HTTP_200_OK
        assert status_response.data["status"] == "success"

    def test_import_status_reports_pending_for_unknown_task(self):
        response = self.api_client.get(path=reverse("youtube-track-list") + "songs/import/does-not-exist/status/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "pending"

    def test_import_rejects_invalid_payload(self):
        response = self.api_client.post(
            path=reverse("youtube-track-list") + "songs/import/", data=[{"title": "Missing"}]
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
