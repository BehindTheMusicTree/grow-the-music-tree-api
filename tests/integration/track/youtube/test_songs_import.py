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
                "youtubeVideoId": "abc123defgh",
                "genreName": "Rock",
            }
        ]

        response = self.api_client.post(path=reverse("youtube-track-list") + "songs/import/", data=payload)

        assert response.status_code == status.HTTP_202_ACCEPTED
        task_id = response.data["task_id"]
        titles = set(YoutubeTrack.objects.filter(user=None).values_list("title", flat=True))
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

    def test_import_sets_then_clears_youtube_unplayable_reason(self):
        self.model_fixture_factory.create_genre("Rock")
        entry = {
            "title": "Comfortably Numb",
            "artist": "Pink Floyd",
            "youtubeVideoId": "abc123defgh",
            "genreName": "Rock",
        }
        path = reverse("youtube-track-list") + "songs/import/"

        response = self.api_client.post(path=path, data=[{**entry, "youtubeUnplayableReason": "not_embeddable"}])
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert YoutubeTrack.objects.get(youtube_video_id="abc123defgh").youtube_unplayable_reason == "not_embeddable"

        response = self.api_client.post(path=path, data=[entry])
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert YoutubeTrack.objects.get(youtube_video_id="abc123defgh").youtube_unplayable_reason is None
