from rest_framework import status
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestMainstreamPopRoot(GenreTestCase):
    def test_missing_mainstream_pop_root_then_400_bad_request(self):
        tree_data = [{Fields.ID: "Q101", Fields.NAME_PUBLIC: "Electronic", Fields.CHILDREN: []}]
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: tree_data}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.DEPENDENCY_MISSING
        assert not Genre.objects.filter(user=None).exists()

    def test_mainstream_pop_root_present_then_201_created(self):
        tree_data = [{Fields.ID: "Q102", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}]
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: tree_data}
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Genre.objects.get(user=None, name="Mainstream Pop", parent=None) is not None

    def test_mainstream_pop_as_non_root_does_not_satisfy_requirement(self):
        tree_data = [
            {
                Fields.ID: "Q104",
                Fields.NAME_PUBLIC: "Electronic",
                Fields.CHILDREN: [{Fields.ID: "Q103", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}],
            }
        ]
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: tree_data}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.DEPENDENCY_MISSING
        assert not Genre.objects.filter(user=None).exists()
