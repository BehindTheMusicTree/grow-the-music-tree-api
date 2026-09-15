from rest_framework import status
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode

from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def test_rename_mainstream_pop_root_away_then_400_bad_request(self):
        root = self.model_fixture_factory.create_genre("Mainstream Pop")

        response = self._put_genre(root.uuid, data={"name": "Pop 2.0"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.DEPENDENCY_MISSING
        root.refresh_from_db()
        assert root.name == "Mainstream Pop"

    def test_reparent_mainstream_pop_root_then_400_bad_request(self):
        other = self.model_fixture_factory.create_genre("Electronic")
        root = self.model_fixture_factory.create_genre("Mainstream Pop")

        response = self._put_genre(root.uuid, data={"parent": str(other.uuid)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.DEPENDENCY_MISSING
        root.refresh_from_db()
        assert root.parent_id is None

    def test_update_unrelated_field_on_mainstream_pop_root_then_200_ok(self):
        root = self.model_fixture_factory.create_genre("Mainstream Pop")
        track = self.model_fixture_factory.create_youtube_track("Strobe", genre=root)

        response = self._put_genre(root.uuid, data={"essential_tracks": [str(track.uuid)]})

        assert response.status_code == status.HTTP_200_OK
        root.refresh_from_db()
        assert list(root.essential_tracks.all()) == [track]
