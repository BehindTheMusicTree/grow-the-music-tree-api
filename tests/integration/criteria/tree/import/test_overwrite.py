from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestOverwrite(GenreTestCase):
    def test_import_new_tree_keeps_existing_genre_without_wikidata_id(self):
        self.model_fixture_factory.create_genre(name="Old Rock")

        tree_data = [
            {Fields.NAME_PUBLIC: "New Rock", Fields.CHILDREN: []},
            {Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []},
        ]
        response = self._post_genres_tree_import(data={Fields.TREE: tree_data})

        assert response.status_code == status.HTTP_201_CREATED

        # "Old Rock" has no wikidataId, so import_criteria_tree never touches it (merge-by-wikidataId).
        genres = Genre.objects.filter(user=self.system_user)
        assert genres.count() == 3
        assert genres.get(name="New Rock") is not None
        assert genres.get(name="Old Rock") is not None
