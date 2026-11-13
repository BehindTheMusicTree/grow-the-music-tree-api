import gzip
import hashlib
import json

from django.core.cache import cache
from django.urls import reverse
from rest_framework import status

from grow.model.artist.Artist import Artist
from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from tests.utils.AppTestCase import AppTestCase


def _snapshot(*region_ids: str) -> RegionMapSnapshot:
    body = json.dumps({"regions": [{"id": region_id} for region_id in region_ids]}).encode()
    sha256 = hashlib.sha256(body).hexdigest()
    compressed = gzip.compress(body)
    RegionMapFile.objects.get_or_create(sha256=sha256, defaults={"body": compressed, "size": len(compressed)})
    RegionMapSnapshot.objects.all().delete()
    return RegionMapSnapshot.objects.create(checksum=sha256)


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        factory = self.model_fixture_factory
        self.band = factory.create_artist("Pink Floyd", type=Artist.Type.GROUP, country="GB", begin_year=1965)
        self.waters = factory.create_artist("Roger Waters", type=Artist.Type.PERSON)
        factory.create_artist_membership(self.band, self.waters, begin_year=1965, end_year=1985, roles=["bass guitar"])
        factory.create_artist_link(self.band, "wikidata", "https://www.wikidata.org/wiki/Q2306")
        album = factory.create_album("The Wall", year="1979", primary_type="Album")
        album.album_artists.set([self.band])
        factory.create_song(title="Comfortably Numb", genre=factory.create_genre("Rock"), artists=[self.band])
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

    def _set_origin(self) -> str:
        Artist.objects.filter(pk=self.band.pk).update(
            origin_name="Liverpool",
            origin_kind="city",
            origin_source="begin_area",
            origin_wikidata_id="Q24826",
            origin_longitude=-2.99,
            origin_latitude=53.41,
            origin_region_id="Q23",
        )
        return reverse("artist-detail", kwargs={"pk": self.band.uuid})

    def test_detail_then_origin_null_until_set(self):
        url = reverse("artist-detail", kwargs={"pk": self.band.uuid})

        assert self.api_client.get(path=url).data["origin"] is None

        _snapshot("Q23")
        self._set_origin()

        assert self.api_client.get(path=url).data["origin"] == {
            "name": "Liverpool",
            "kind": "city",
            "source": "begin_area",
            "wikidata_id": "Q24826",
            "longitude": -2.99,
            "latitude": 53.41,
            "region_id": "Q23",
        }

    def test_detail_then_origin_region_null_without_snapshot(self):
        url = self._set_origin()

        origin = self.api_client.get(path=url).data["origin"]

        assert (origin["name"], origin["region_id"]) == ("Liverpool", None)

    def test_detail_then_origin_region_null_when_not_drawn(self):
        url = self._set_origin()
        _snapshot("Q1")

        assert self.api_client.get(path=url).data["origin"]["region_id"] is None

    def test_detail_then_origin_region_follows_the_latest_snapshot(self):
        url = self._set_origin()
        _snapshot("Q1")
        assert self.api_client.get(path=url).data["origin"]["region_id"] is None

        _snapshot("Q1", "Q23")

        assert self.api_client.get(path=url).data["origin"]["region_id"] == "Q23"

    def test_detail_then_playable_tracks_count_excludes_unplayable_songs(self):
        factory = self.model_fixture_factory
        prog = factory.create_genre("Prog")
        factory.create_song(title="No Video", genre=prog, artists=[self.band], youtube_video_id=None)
        factory.create_song(
            title="Blocked", genre=prog, artists=[self.band], youtube_unplayable_reason="embedding_disabled"
        )

        response = self.api_client.get(path=reverse("artist-detail", kwargs={"pk": self.band.uuid}))

        assert (response.data["tracks_count"], response.data["playable_tracks_count"]) == (3, 1)

    def test_unknown_artist_then_404(self):
        response = self.api_client.get(
            path=reverse("artist-detail", kwargs={"pk": "0c4b2a83-6a5c-4c1d-9f43-3b9d8f0b2e11"})
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
