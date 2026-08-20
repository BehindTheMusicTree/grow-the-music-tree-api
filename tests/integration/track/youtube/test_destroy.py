from django.urls import reverse
from rest_framework import status

from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_destroy_removes_track(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        youtube_track = self.model_fixture_factory.create_youtube_track(title="Track Title", genre=genre)

        response = self.api_client.delete(path=reverse("youtube-track-detail", kwargs={"pk": youtube_track.uuid}))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not YoutubeTrack.objects.filter(uuid=youtube_track.uuid).exists()
