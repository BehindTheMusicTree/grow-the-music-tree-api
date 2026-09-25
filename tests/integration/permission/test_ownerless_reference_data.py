from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.urls import reverse
from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.permission.test_google_id_token_auth import VERIFY, VIEWER_CLAIMS
from tests.integration.permission.test_pipeline_scope import TREE_PAYLOAD
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_anonymous_get_then_canonical_rows(self):
        self.model_fixture_factory.create_genre(name="Rock")
        self.api_client.credentials()

        response = self.api_client.get(path=reverse("genre-list"))

        assert response.status_code == status.HTTP_200_OK
        assert "Rock" in response.content.decode()

    def test_anonymous_get_tree_on_empty_dataset_then_200(self):
        self.api_client.credentials()

        response = self.api_client.get(path=reverse("genre-list") + "tree/")

        assert response.status_code == status.HTTP_200_OK

    def test_admin_write_then_ownerless_row(self):
        response = self.api_client.post(path=reverse("genre-list"), data={"name": "Rock"})

        assert response.status_code == status.HTTP_201_CREATED
        assert Genre.objects.get(name="Rock").user is None

    def test_pipeline_tree_import_then_ownerless_rows(self):
        self.api_client.credentials(HTTP_X_API_KEY="test-api-key")

        response = self.api_client.post(path=reverse("genre-list") + "tree/import/", data=TREE_PAYLOAD)

        assert response.status_code == status.HTTP_201_CREATED
        assert Genre.objects.count() == 2
        assert not Genre.objects.filter(user__isnull=False).exists()

    def test_google_sign_in_then_user_keyed_by_sub(self):
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            self.api_client.get(path=reverse("genre-list"))
            self.api_client.get(path=reverse("genre-list"))

        user = User.objects.get(username=VIEWER_CLAIMS["sub"])
        assert user.email == VIEWER_CLAIMS["email"]

    def test_duplicate_canonical_name_then_integrity_error(self):
        self.model_fixture_factory.create_genre(name="Rock")

        with self.assertRaises(IntegrityError):
            self.model_fixture_factory.create_genre(name="Rock")

    def test_same_name_canonical_and_personal_then_allowed(self):
        self.model_fixture_factory.create_genre(name="Rock")

        self.model_fixture_factory.create_genre(name="Rock", user=User.objects.create(username="someone"))
