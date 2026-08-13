from typing import cast

from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestOverwrite(GenreTestCase):
    def test_import_new_tree_then_overwrites_existing(self):
        self.model_fixture_factory.create_genre(name="Old Rock")

        tree_data = [{Fields.NAME_PUBLIC: "New Rock", Fields.CHILDREN: []}]
        response = self._post_genres_tree_import(data={Fields.TREE: tree_data})

        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=self.system_user)
        assert genres.count() == 1
        assert cast(Genre, genres.first()).name == "New Rock"
