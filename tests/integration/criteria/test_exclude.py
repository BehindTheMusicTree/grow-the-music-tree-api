from rest_framework import status
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode

from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def test_exclude_genre_then_200_and_flag_set_and_history_logged(self):
        genre = self.model_fixture_factory.create_genre("Electronic")

        response = self._post_genre_exclude(genre.uuid)

        assert response.status_code == status.HTTP_200_OK
        genre.refresh_from_db()
        assert genre.is_excluded is True
        entry = HistoryEntry.objects.get(content_uuid=genre.uuid, action=HistoryAction.EXCLUDED)
        assert entry.actor_email == "admin@example.com"

    def test_exclude_sole_mainstream_pop_root_then_400_bad_request(self):
        root = self.model_fixture_factory.create_genre("Mainstream Pop")

        response = self._post_genre_exclude(root.uuid)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.bad_request_result_field_errors[0]["code"] == FieldValidationErrorCode.DEPENDENCY_MISSING
        root.refresh_from_db()
        assert root.is_excluded is False
