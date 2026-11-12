from rest_framework import status

from tests.integration.criteria.GenreTestCase import GenreTestCase
from tests.utils.essential_songs import add_essential_song


class TestCase(GenreTestCase):
    def test_sets_essential_songs(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        track = self.model_fixture_factory.create_song("Strobe", genre=genre)

        response = self._put_genre(genre.uuid, data={"essentialSongs": [str(track.uuid)]})

        assert response.status_code == status.HTTP_200_OK
        genre.refresh_from_db()
        assert list(genre.essential_songs.all()) == [track]

    def test_clears_essential_songs(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        track = self.model_fixture_factory.create_song("Strobe", genre=genre)
        add_essential_song(genre, track)

        response = self._put_genre(genre.uuid, data={"essentialSongs": []})

        assert response.status_code == status.HTTP_200_OK
        genre.refresh_from_db()
        assert list(genre.essential_songs.all()) == []
