from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def test_creates_genre_with_essential_songs(self):
        genre = self.model_fixture_factory.create_genre("Electronic", wikidata_id="Q1")
        track = self.model_fixture_factory.create_song("Strobe", genre=genre)

        response = self._post_genre(
            data={"name": "EDM", "parent": str(genre.uuid), "essentialSongs": [str(track.uuid)]}
        )

        assert response.status_code == status.HTTP_201_CREATED
        created = Genre.objects.get(uuid=response.json()["uuid"])
        assert list(created.essential_songs.all()) == [track]

    def test_creates_genre_without_essential_songs(self):
        parent = self.model_fixture_factory.create_genre("Music", wikidata_id="Q1")

        response = self._post_genre(data={"name": "Rock", "parent": str(parent.uuid)})

        assert response.status_code == status.HTTP_201_CREATED
        created = Genre.objects.get(uuid=response.json()["uuid"])
        assert list(created.essential_songs.all()) == []
