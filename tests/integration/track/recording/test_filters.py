from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    list_endpoint = "recording-list"

    def setUp(self):
        super().setUp()
        self.rock = self.model_fixture_factory.create_genre("Rock")
        self.jazz = self.model_fixture_factory.create_genre("Jazz")
        self.pink_floyd = self.model_fixture_factory.create_artist("Pink Floyd")
        self.album = self.model_fixture_factory.create_album("The Wall")
        self.matching_track = self.model_fixture_factory.create_recording(
            title="Comfortably Numb",
            genre=self.rock,
            artists=[self.pink_floyd],
            album=self.album,
            language="en",
        )
        self.other_track = self.model_fixture_factory.create_recording(
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

    def test_filter_by_genre_covers_primary_descendants_regardless_of_video(self):
        prog = self.model_fixture_factory.create_genre("Progressive Rock", parent=self.rock)
        prog_track = self.model_fixture_factory.create_recording(title="Echoes", genre=prog, youtube_video_id=None)

        assert self._list_uuids(genre=str(self.rock.uuid)) == {str(self.matching_track.uuid), str(prog_track.uuid)}
        assert self._list_uuids(genre=str(prog.uuid)) == {str(prog_track.uuid)}

    def test_filter_by_language(self):
        assert self._list_uuids(language="en") == {str(self.matching_track.uuid)}

    def test_filter_with_no_match_then_empty(self):
        assert self._list_uuids(title="nonexistent") == set()

    def test_filter_by_artist_uuid(self):
        assert self._list_uuids(artist=str(self.pink_floyd.uuid)) == {str(self.matching_track.uuid)}

    def test_ordering_by_title_and_album_year(self):
        type(self.album).objects.filter(pk=self.album.pk).update(year="1979")
        self.model_fixture_factory.create_recording(
            title="Echoes", genre=self.rock, album=self.model_fixture_factory.create_album("Meddle", year="1971")
        )

        def titles(ordering):
            response = self.api_client.get(path=reverse(self.list_endpoint), data={"ordering": ordering})
            return [track["title"] for track in response.data["results"]]

        assert titles("title") == ["Comfortably Numb", "Echoes", "So What"]
        assert titles("-title") == ["So What", "Echoes", "Comfortably Numb"]
        assert titles("albumYear") == ["Echoes", "Comfortably Numb", "So What"]
        assert titles("-albumYear") == ["Comfortably Numb", "Echoes", "So What"]

    def test_unknown_ordering_then_400(self):
        response = self.api_client.get(path=reverse(self.list_endpoint), data={"ordering": "genre"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
