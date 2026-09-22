import pytest
from the_music_tree_api_kit.exception.validation.app.AppValidationException import AppValidationException

from grow.model.criteria.children.genre.Genre import Genre
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_assert_required_roots_present_raises_when_absent(self):
        self.model_fixture_factory.create_genre("Electronic")

        with pytest.raises(AppValidationException):
            Genre.objects.assert_required_roots_present(self.system_user)

    def test_assert_required_roots_present_does_not_raise_when_present(self):
        self.model_fixture_factory.create_genre("Mainstream Pop")

        Genre.objects.assert_required_roots_present(self.system_user)

    def test_assert_required_roots_present_requires_root_placement(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        self.model_fixture_factory.create_genre("Mainstream Pop", parent=root)

        with pytest.raises(AppValidationException):
            Genre.objects.assert_required_roots_present(self.system_user)

    def test_delete_instance_on_sole_required_root_raises_and_rolls_back(self):
        root = self.model_fixture_factory.create_genre("Mainstream Pop")
        root_pk = root.pk

        with pytest.raises(AppValidationException):
            Genre.objects.delete_instance(root)

        assert Genre.objects.filter(pk=root_pk).exists()

    def test_delete_instance_on_unrelated_genre_succeeds_when_required_root_already_missing(self):
        electronic = self.model_fixture_factory.create_genre("Electronic")

        Genre.objects.delete_instance(electronic)

        assert not Genre.objects.filter(pk=electronic.pk).exists()

    def test_update_instance_renaming_required_root_away_raises_and_rolls_back(self):
        root = self.model_fixture_factory.create_genre("Mainstream Pop")

        with pytest.raises(AppValidationException):
            Genre.objects.update_instance(root, name="Pop 2.0")

        root.refresh_from_db()
        assert root.name == "Mainstream Pop"

    def test_update_instance_reparenting_required_root_raises_and_rolls_back(self):
        other = self.model_fixture_factory.create_genre("Electronic")
        root = self.model_fixture_factory.create_genre("Mainstream Pop")

        with pytest.raises(AppValidationException):
            Genre.objects.update_instance(root, parent=other)

        root.refresh_from_db()
        assert root.parent_id is None

    def test_update_instance_on_required_root_unrelated_field_succeeds(self):
        root = self.model_fixture_factory.create_genre("Mainstream Pop")

        updated = Genre.objects.update_instance(root, summary="A short blurb.")

        assert updated.summary == "A short blurb."
