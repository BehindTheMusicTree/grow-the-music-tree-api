from unittest.mock import patch

from django.conf import settings
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from tests.integration.permission.test_google_id_token_auth import VERIFY, VIEWER_CLAIMS
from tests.utils.AppTestCase import AppTestCase

TREE_PAYLOAD = {Fields.TREE: [{Fields.NAME_PUBLIC: n, Fields.CHILDREN: []} for n in ("Rock", "Mainstream Pop")]}
SONG = {"title": "Comfortably Numb", "artist": "Pink Floyd", "youtube_video_id": "abc123defgh", "genre_name": "Rock"}


class TestCase(AppTestCase):
    def _tree_import(self):
        return self.api_client.post(path=reverse("genre-list") + "tree/import/", data=TREE_PAYLOAD)

    def _songs_import(self):
        return self.api_client.post(path=reverse("youtube-track-list") + "songs/import/", data=[SONG])

    def _use_api_key(self):
        self.api_client.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

    def test_api_key_tree_import_then_201(self):
        self._use_api_key()

        assert self._tree_import().status_code == status.HTTP_201_CREATED

    def test_api_key_songs_import_then_202(self):
        self.model_fixture_factory.create_genre("Rock")
        self._use_api_key()

        assert self._songs_import().status_code == status.HTTP_202_ACCEPTED

    def test_api_key_other_write_then_403(self):
        self._use_api_key()

        response = self.api_client.post(path=reverse("genre-list"), data={"name": "Rock"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["details"]["code"] == "permission_denied"

    def test_viewer_token_imports_then_403(self):
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            responses = [self._tree_import(), self._songs_import()]

        assert [r.status_code for r in responses] == [status.HTTP_403_FORBIDDEN] * 2

    def test_anonymous_imports_then_401(self):
        self.api_client.credentials()

        responses = [self._tree_import(), self._songs_import()]

        assert [r.status_code for r in responses] == [status.HTTP_401_UNAUTHORIZED] * 2
        assert {r.json()["details"]["code"] for r in responses} == {"authentication_required"}
