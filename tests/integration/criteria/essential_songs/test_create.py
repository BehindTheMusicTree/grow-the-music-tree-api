from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def test_creates_genre_with_essential_songs(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        track = self.model_fixture_factory.create_song("Strobe", genre=genre)

        response = self._post_genre(data={"name": "EDM", "essentialSongs": [str(track.uuid)]})

        assert response.status_code == status.HTTP_201_CREATED
        created = Genre.objects.get(uuid=response.json()["uuid"])
        assert list(created.essential_songs.all()) == [track]

    def test_creates_genre_without_essential_songs(self):
        response = self._post_genre(data={"name": "Rock"})

        assert response.status_code == status.HTTP_201_CREATED
        created = Genre.objects.get(uuid=response.json()["uuid"])
        assert list(created.essential_songs.all()) == []

    def test_accepts_deprecated_essential_tracks_key(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        track = self.model_fixture_factory.create_song("Strobe", genre=genre)

        response = self._post_genre(data={"name": "EDM", "essentialTracks": [str(track.uuid)]})

        assert response.status_code == status.HTTP_201_CREATED
        assert list(Genre.objects.get(uuid=response.json()["uuid"]).essential_songs.all()) == [track]

    def test_essential_songs_wins_over_deprecated_essential_tracks(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        wanted = self.model_fixture_factory.create_song("Strobe", genre=genre)
        ignored = self.model_fixture_factory.create_song("Ghosts", genre=genre)

        response = self._post_genre(
            data={"name": "EDM", "essentialSongs": [str(wanted.uuid)], "essentialTracks": [str(ignored.uuid)]}
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert list(Genre.objects.get(uuid=response.json()["uuid"]).essential_songs.all()) == [wanted]
