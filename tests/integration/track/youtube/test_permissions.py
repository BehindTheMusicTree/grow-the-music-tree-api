from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    list_endpoint = "youtube-track-list"

    def test_get_without_api_key_then_200_ok(self):
        self.api_client.credentials()

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK

    def test_delete_without_api_key_then_401_unauthorized(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        youtube_track = self.model_fixture_factory.create_youtube_track(title="Track Title", genre=genre)
        self.api_client.credentials()

        response = self.api_client.delete(path=reverse("youtube-track-detail", kwargs={"pk": youtube_track.uuid}))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_with_api_key_then_not_401_unauthorized(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        youtube_track = self.model_fixture_factory.create_youtube_track(title="Track Title", genre=genre)

        response = self.api_client.delete(path=reverse("youtube-track-detail", kwargs={"pk": youtube_track.uuid}))

        assert response.status_code != status.HTTP_401_UNAUTHORIZED

    def test_post_with_api_key_then_405_method_not_allowed(self):
        response = self.api_client.post(path=reverse(self.list_endpoint), data={"title": "Track Title"})

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
