from django.urls import reverse
from rest_framework import status

from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_destroy_removes_track(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        song = self.model_fixture_factory.create_song(title="Track Title", genre=genre)

        response = self.api_client.delete(path=reverse("song-detail", kwargs={"pk": song.uuid}))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Song.objects.filter(uuid=song.uuid).exists()
