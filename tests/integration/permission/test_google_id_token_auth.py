from unittest.mock import patch

from django.conf import settings
from django.urls import reverse
from google.auth.exceptions import TransportError
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase

VERIFY = "grow.authentication.GoogleIdTokenAuthentication.id_token.verify_oauth2_token"
ADMIN_CLAIMS = {"sub": settings.ADMIN_GOOGLE_SUB, "email": "admin@example.com", "email_verified": True}
VIEWER_CLAIMS = {"sub": "someone-else", "email": "viewer@example.com", "email_verified": True}


class TestCase(AppTestCase):
    list_endpoint = "genre-list"

    def _use_token(self):
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")

    def _post_genre(self):
        return self.api_client.post(path=reverse(self.list_endpoint), data={"name": "Rock"})

    def test_admin_token_write_then_201(self):
        self._use_token()
        with patch(VERIFY, return_value=ADMIN_CLAIMS) as verify:
            response = self._post_genre()

        assert response.status_code == status.HTTP_201_CREATED
        assert verify.call_args.kwargs["audience"] == settings.GOOGLE_OAUTH_CLIENT_ID

    def test_viewer_token_write_then_403_permission_denied(self):
        self._use_token()
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            response = self._post_genre()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["details"]["code"] == "permission_denied"

    def test_viewer_token_get_then_200(self):
        self._use_token()
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK

    def test_invalid_token_then_401_invalid_token(self):
        self._use_token()
        with patch(VERIFY, side_effect=ValueError("Token expired")):
            response = self._post_genre()

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["details"]["code"] == "invalid_token"

    def test_google_unreachable_then_503_auth_provider_unavailable(self):
        self._use_token()
        with patch(VERIFY, side_effect=TransportError("certs fetch failed")):
            response = self._post_genre()

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["details"]["code"] == "auth_provider_unavailable"

    def test_unverified_email_then_401_invalid_token(self):
        self._use_token()
        with patch(VERIFY, return_value={**ADMIN_CLAIMS, "email_verified": False}):
            response = self._post_genre()

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["details"]["code"] == "invalid_token"

    def test_anonymous_write_then_401_authentication_required(self):
        self.api_client.credentials()

        response = self._post_genre()

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["details"]["code"] == "authentication_required"

    def test_default_client_admin_write_then_201(self):
        response = self._post_genre()

        assert response.status_code == status.HTTP_201_CREATED


class TestAuthMe(AppTestCase):
    def _me(self):
        return self.api_client.get(path=reverse("auth-me"))

    def test_admin(self):
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")
        with patch(VERIFY, return_value=ADMIN_CLAIMS):
            response = self._me()

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"role": "admin", "email": "admin@example.com"}

    def test_viewer(self):
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            response = self._me()

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"role": "viewer", "email": "viewer@example.com"}

    def test_pipeline(self):
        self.api_client.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

        response = self._me()

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"role": "pipeline", "email": None}

    def test_anonymous_then_401(self):
        self.api_client.credentials()

        response = self._me()

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["details"]["code"] == "authentication_required"
