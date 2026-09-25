from django.urls import reverse
from rest_framework import status

from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_history_returns_genre_changed_entry(self):
        rock = self.model_fixture_factory.create_genre(name="Rock")
        pop = self.model_fixture_factory.create_genre(name="Pop")
        track = self.model_fixture_factory.create_youtube_track(title="wech", genre=rock)
        YoutubeTrack.objects.update_instance(track, genre=pop, actor="admin@example.com")

        response = self.api_client.get(path=reverse("youtube-track-detail", kwargs={"pk": track.uuid}) + "history/")

        assert response.status_code == status.HTTP_200_OK
        actions = [entry["action"] for entry in response.data]
        assert "genre_changed" in actions
        entry = next(entry for entry in response.data if entry["action"] == "genre_changed")
        assert entry["actor_email"] == "admin@example.com"
        assert entry["old_value"] == "Rock"
        assert entry["new_value"] == "Pop"
