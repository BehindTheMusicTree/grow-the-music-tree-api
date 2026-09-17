from rest_framework import status
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def test_delete_sole_mainstream_pop_root_then_400_bad_request(self):
        root = self.model_fixture_factory.create_genre("Mainstream Pop")

        response = self._delete_genre(root.uuid)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.DEPENDENCY_MISSING
        assert Genre.objects.filter(pk=root.pk).exists()

    def test_delete_unrelated_genre_then_204_no_content(self):
        self.model_fixture_factory.create_genre("Mainstream Pop")
        electronic = self.model_fixture_factory.create_genre("Electronic")

        response = self._delete_genre(electronic.uuid)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Genre.objects.filter(pk=electronic.pk).exists()
