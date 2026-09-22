from rest_framework import status

from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def test_sets_essential_tracks(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        track = self.model_fixture_factory.create_youtube_track("Strobe", genre=genre)

        response = self._put_genre(genre.uuid, data={"essential_tracks": [str(track.uuid)]})

        assert response.status_code == status.HTTP_200_OK
        genre.refresh_from_db()
        assert list(genre.essential_tracks.all()) == [track]

    def test_clears_essential_tracks(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        track = self.model_fixture_factory.create_youtube_track("Strobe", genre=genre)
        genre.essential_tracks.add(track)

        response = self._put_genre(genre.uuid, data={"essential_tracks": []})

        assert response.status_code == status.HTTP_200_OK
        genre.refresh_from_db()
        assert list(genre.essential_tracks.all()) == []
