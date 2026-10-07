import uuid

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from tests.utils.AppTestCase import AppTestCase

MBID = "b1a9c0e9-d987-4042-ae91-78d6a3267d69"


class TestCase(AppTestCase):
    def test_import_creates_tracks_from_payload(self):
        self.model_fixture_factory.create_genre("Rock")
        payload = [
            {
                "title": "Comfortably Numb",
                "artist": "Pink Floyd",
                "youtubeVideoId": "abc123defgh",
                "musicbrainzRecordingId": MBID,
                "genreName": "Rock",
            }
        ]

        response = self.api_client.post(path=reverse("youtube-track-list") + "songs/import/", data=payload)

        assert response.status_code == status.HTTP_202_ACCEPTED
        task_id = response.data["task_id"]
        track = YoutubeTrack.objects.get(user=None)
        assert track.title == "Comfortably Numb"
        assert track.musicbrainz_recording_id == uuid.UUID(MBID)

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

    # Prod's CamelToSnakeMiddleware reads request.body, which is where Django enforces the upload limit.
    @override_settings(
        MIDDLEWARE=[
            *settings.MIDDLEWARE,
            "the_music_tree_api_kit.view.middleware.CamelToSnakeMiddleware.CamelToSnakeMiddleware",
        ]
    )
    def test_import_reads_body_above_django_default_upload_limit(self):
        payload = [
            {
                "title": "x" * 3 * 1024 * 1024,
                "artist": "Pink Floyd",
                "youtubeVideoId": "abc123defgh",
                "musicbrainzRecordingId": MBID,
                "genreName": "Rock",
            }
        ]

        response = self.api_client.post(path=reverse("youtube-track-list") + "songs/import/", data=payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "title" in response.json()["details"]["fieldErrors"]

    def test_import_sets_then_clears_youtube_unplayable_reason(self):
        self.model_fixture_factory.create_genre("Rock")
        entry = {
            "title": "Comfortably Numb",
            "artist": "Pink Floyd",
            "youtubeVideoId": "abc123defgh",
            "musicbrainzRecordingId": MBID,
            "genreName": "Rock",
        }
        path = reverse("youtube-track-list") + "songs/import/"

        response = self.api_client.post(path=path, data=[{**entry, "youtubeUnplayableReason": "not_embeddable"}])
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert YoutubeTrack.objects.get(youtube_video_id="abc123defgh").youtube_unplayable_reason == "not_embeddable"

        response = self.api_client.post(path=path, data=[entry])
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert YoutubeTrack.objects.get(youtube_video_id="abc123defgh").youtube_unplayable_reason is None

    def test_import_rejects_entry_without_musicbrainz_recording_id(self):
        self.model_fixture_factory.create_genre("Rock")
        entry = {
            "title": "Comfortably Numb",
            "artist": "Pink Floyd",
            "youtubeVideoId": "abc123defgh",
            "genreName": "Rock",
        }

        response = self.api_client.post(path=reverse("youtube-track-list") + "songs/import/", data=[entry])

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_import_adopts_legacy_track_by_video_id_then_follows_video_id_change(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        legacy = self.model_fixture_factory.create_youtube_track(
            title="Comfortably Numb", genre=genre, user=None, youtube_video_id="abc123defgh"
        )
        entry = {
            "title": "Comfortably Numb",
            "artist": "Pink Floyd",
            "youtubeVideoId": "abc123defgh",
            "musicbrainzRecordingId": MBID,
            "genreName": "Rock",
        }
        path = reverse("youtube-track-list") + "songs/import/"

        response = self.api_client.post(path=path, data=[entry])
        assert response.status_code == status.HTTP_202_ACCEPTED
        legacy.refresh_from_db()
        assert legacy.musicbrainz_recording_id == uuid.UUID(MBID)

        response = self.api_client.post(path=path, data=[{**entry, "youtubeVideoId": "xyz789uvwab"}])
        assert response.status_code == status.HTTP_202_ACCEPTED
        track = YoutubeTrack.objects.get(user=None)
        assert track.uuid == legacy.uuid
        assert track.youtube_video_id == "xyz789uvwab"
