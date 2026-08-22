from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    list_endpoint = "youtube-track-list"

    def setUp(self):
        super().setUp()
        self.rock = self.model_fixture_factory.create_genre("Rock")
        self.jazz = self.model_fixture_factory.create_genre("Jazz")
        self.pink_floyd = self.model_fixture_factory.create_artist("Pink Floyd")
        self.album = self.model_fixture_factory.create_album("The Wall")
        self.matching_track = self.model_fixture_factory.create_youtube_track(
            title="Comfortably Numb",
            genre=self.rock,
            artists=[self.pink_floyd],
            album=self.album,
            language="en",
        )
        self.other_track = self.model_fixture_factory.create_youtube_track(
            title="So What",
            genre=self.jazz,
            language="fr",
        )

    def _list_uuids(self, **params):
        response = self.api_client.get(path=reverse(self.list_endpoint), data=params)
        assert response.status_code == status.HTTP_200_OK
        return {track["uuid"] for track in response.data["results"]}

    def test_filter_by_title(self):
        assert self._list_uuids(title="comfortably") == {str(self.matching_track.uuid)}

    def test_filter_by_artists_name(self):
        assert self._list_uuids(artists_name="pink floyd") == {str(self.matching_track.uuid)}

    def test_filter_by_album_name(self):
        assert self._list_uuids(album_name="the wall") == {str(self.matching_track.uuid)}

    def test_filter_by_genre_name(self):
        assert self._list_uuids(genre_name="rock") == {str(self.matching_track.uuid)}

    def test_filter_by_language(self):
        assert self._list_uuids(language="en") == {str(self.matching_track.uuid)}

    def test_filter_with_no_match_then_empty(self):
        assert self._list_uuids(title="nonexistent") == set()
