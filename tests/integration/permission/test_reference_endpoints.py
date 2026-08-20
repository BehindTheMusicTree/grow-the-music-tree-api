from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    list_endpoint = "reference-genre-list"

    def test_get_without_api_key_then_200_ok(self):
        self.api_client.credentials()

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK

    def test_post_without_api_key_then_401_unauthorized(self):
        self.api_client.credentials()

        response = self.api_client.post(path=reverse(self.list_endpoint), data={"name": "Rock"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_post_with_api_key_then_not_401_unauthorized(self):
        response = self.api_client.post(path=reverse(self.list_endpoint), data={"name": "Rock"})

        assert response.status_code != status.HTTP_401_UNAUTHORIZED
