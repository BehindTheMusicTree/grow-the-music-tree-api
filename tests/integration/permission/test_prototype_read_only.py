from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    list_endpoint = "genre-list"

    def test_get_with_prototype_api_key_then_200_ok(self):
        response = self.prototype_api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK

    def test_post_with_prototype_api_key_then_403_forbidden(self):
        response = self.prototype_api_client.post(path=reverse(self.list_endpoint), data={"name": "Rock"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["details"]["message"] == "The prototype API key is read-only"

    def test_post_with_system_api_key_then_not_403_forbidden(self):
        response = self.api_client.post(path=reverse(self.list_endpoint), data={"name": "Rock"})

        assert response.status_code != status.HTTP_403_FORBIDDEN

    def test_delete_with_prototype_api_key_then_403_forbidden(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        youtube_track = self.model_fixture_factory.create_youtube_track(title="Track Title", genre=genre)

        response = self.prototype_api_client.delete(
            path=reverse("youtube-track-detail", kwargs={"pk": youtube_track.uuid})
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["details"]["message"] == "The prototype API key is read-only"
