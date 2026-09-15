import pytest
from the_music_tree_api_kit.exception.validation.app.AppValidationException import AppValidationException

from grow.model.criteria.children.genre.Genre import Genre
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_assert_mainstream_pop_root_present_raises_when_absent(self):
        self.model_fixture_factory.create_genre("Electronic")

        with pytest.raises(AppValidationException):
            Genre.objects.assert_mainstream_pop_root_present(self.system_user)

    def test_assert_mainstream_pop_root_present_does_not_raise_when_present(self):
        self.model_fixture_factory.create_genre("Mainstream Pop")

        Genre.objects.assert_mainstream_pop_root_present(self.system_user)

    def test_assert_mainstream_pop_root_present_requires_root_placement(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        self.model_fixture_factory.create_genre("Mainstream Pop", parent=root)

        with pytest.raises(AppValidationException):
            Genre.objects.assert_mainstream_pop_root_present(self.system_user)
