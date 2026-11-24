from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_anonymous_detail_lists_the_album_tracks(self):
        factory = self.model_fixture_factory
        album = factory.create_album("The Wall", year="1979", primary_type="Album")
        artist = factory.create_artist("Pink Floyd")
        album.album_artists.set([artist])
        factory.create_song(title="Comfortably Numb", genre=factory.create_genre("Rock"), artists=[artist], album=album)
        self.api_client.credentials()

        response = self.api_client.get(path=reverse("album-detail", kwargs={"pk": album.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["tracks_count"] == 1
        assert [track["title"] for track in response.data["tracks_sorted"]] == ["Comfortably Numb"]
