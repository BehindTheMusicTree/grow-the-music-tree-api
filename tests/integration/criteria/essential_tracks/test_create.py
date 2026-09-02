from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def test_creates_genre_with_essential_tracks(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        track = self.model_fixture_factory.create_youtube_track("Strobe", genre=genre)

        response = self._post_genre(data={"name": "EDM", "essential_tracks": [str(track.uuid)]})

        assert response.status_code == status.HTTP_201_CREATED
        created = Genre.objects.get(uuid=response.json()["uuid"])
        assert list(created.essential_tracks.all()) == [track]

    def test_creates_genre_without_essential_tracks(self):
        response = self._post_genre(data={"name": "Rock"})

        assert response.status_code == status.HTTP_201_CREATED
        created = Genre.objects.get(uuid=response.json()["uuid"])
        assert list(created.essential_tracks.all()) == []
