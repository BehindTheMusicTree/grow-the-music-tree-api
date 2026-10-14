from django.urls import reverse
from rest_framework import status

from grow.model.artist.Artist import Artist
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        factory = self.model_fixture_factory
        self.band = factory.create_artist("Pink Floyd", type=Artist.Type.GROUP, country="GB", begin_year=1965)
        self.waters = factory.create_artist("Roger Waters", type=Artist.Type.PERSON)
        factory.create_artist_membership(self.band, self.waters, begin_year=1965, end_year=1985, roles=["bass guitar"])
        factory.create_artist_link(self.band, "wikidata", "https://www.wikidata.org/wiki/Q2306")
        album = factory.create_album("The Wall", year="1979", primary_type="Album")
        album.album_artists.set([self.band])
        factory.create_recording(title="Comfortably Numb", genre=factory.create_genre("Rock"), artists=[self.band])
        self.api_client.credentials()

    def test_anonymous_list_then_simple_shape(self):
        response = self.api_client.get(path=reverse("artist-list"), data={"name": "pink"})

        assert response.status_code == status.HTTP_200_OK
        (artist,) = response.data["results"]
        assert (artist["name"], artist["tracks_count"], artist["albums"][0]["name"]) == ("Pink Floyd", 1, "The Wall")
        assert "tracks" not in artist

    def test_anonymous_detail_then_artist_page_shape(self):
        response = self.api_client.get(path=reverse("artist-detail", kwargs={"pk": self.band.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert (response.data["type"], response.data["country"], response.data["tracks_count"]) == ("group", "GB", 1)
        assert response.data["members"][0]["artist"]["name"] == "Roger Waters"
        assert response.data["links"] == [{"kind": "wikidata", "url": "https://www.wikidata.org/wiki/Q2306"}]
        assert response.data["albums"][0]["primary_type"] == "Album"

    def test_unknown_artist_then_404(self):
        response = self.api_client.get(
            path=reverse("artist-detail", kwargs={"pk": "0c4b2a83-6a5c-4c1d-9f43-3b9d8f0b2e11"})
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
