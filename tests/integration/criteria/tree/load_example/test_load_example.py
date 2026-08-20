from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestLoadExample(GenreTestCase):
    def test_load_example_tree_creates_genres_from_fixture(self):
        response = self._post_genres_tree_load_example()
        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=self.system_user)
        assert genres.count() > 0
        electronic = genres.get(name="Electronic", parent=None)
        house = genres.get(name="House", parent=electronic)
        assert genres.get(name="Deep House", parent=house) is not None

    def test_load_example_tree_replaces_existing_genres(self):
        self.model_fixture_factory.create_genre(name="Old Rock")

        response = self._post_genres_tree_load_example()
        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=self.system_user)
        assert not genres.filter(name="Old Rock").exists()
        assert genres.filter(name="Rock/Metal", parent=None).exists()
