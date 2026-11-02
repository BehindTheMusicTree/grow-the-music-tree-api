from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.Fields import Fields as CriteriaFields
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def _import(self, root_name, side):
        child = {Fields.ID: "Q102", Fields.NAME_PUBLIC: "Teen pop", CriteriaFields.SIDE: side, Fields.CHILDREN: []}
        root = {Fields.ID: "Q373342", Fields.NAME_PUBLIC: root_name, Fields.CHILDREN: [child]}
        required = {Fields.ID: "Q373343", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}
        tree = [root] if root_name == "Mainstream Pop" else [required, root]
        return self._post_genres_tree_import(data={Fields.TREE_NAME: "canonical", Fields.TREE: tree})

    def test_pop_child_under_mainstream_pop_then_rejected(self):
        response = self._import("Mainstream Pop", "pop")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Genre.objects.filter(wikidata_id="Q102").exists()

    def test_pop_child_under_other_root_then_imported(self):
        response = self._import("Rock music", "pop")

        assert response.status_code == status.HTTP_201_CREATED
        assert Genre.objects.get(wikidata_id="Q102").side == "pop"
