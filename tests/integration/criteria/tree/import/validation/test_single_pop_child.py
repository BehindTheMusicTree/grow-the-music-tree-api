from rest_framework import status
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestSinglePopChild(GenreTestCase):
    def test_two_pop_children_for_one_root_then_400_bad_request(self):
        tree_data = [
            {Fields.ID: "Q1", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []},
            {
                Fields.ID: "Q2",
                Fields.NAME_PUBLIC: "Rock",
                Fields.CHILDREN: [
                    {
                        Fields.ID: "Q3",
                        Fields.NAME_PUBLIC: "Pop rock",
                        Fields.SIDE: CriteriaSide.POP,
                        Fields.CHILDREN: [],
                    },
                    {
                        Fields.ID: "Q4",
                        Fields.NAME_PUBLIC: "Soft rock",
                        Fields.SIDE: CriteriaSide.POP,
                        Fields.CHILDREN: [],
                    },
                ],
            },
        ]
        response = self._post_genres_tree_import(data={Fields.TREE_NAME: "canonical", Fields.TREE: tree_data})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.REFERENCE_INVALID
        assert not Genre.objects.filter(user=None).exists()
