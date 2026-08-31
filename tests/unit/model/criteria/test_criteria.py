import pytest
from the_music_tree_api_kit.exception.validation.app.AppValidationException import AppValidationException
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_create_tag_with_side_raises_dependency_missing(self):
        with pytest.raises(AppValidationException) as exc_info:
            self.model_fixture_factory.create_tag("Instrumental", side=CriteriaSide.POP)

        assert exc_info.value.field_validation_error_code == FieldValidationErrorCode.DEPENDENCY_MISSING
