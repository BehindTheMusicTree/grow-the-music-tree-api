import requests
from django.conf import settings
from django.contrib.auth.models import User
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from grow.authentication.Principal import Principal
from grow.model.user.get_system_user import get_system_user

_google_request = GoogleRequest(session=requests.Session())


class GoogleIdTokenAuthentication(BaseAuthentication):
    """
    Verifies a Google ID token from `Authorization: Bearer <token>`. Every principal acts on the system user;
    the role (admin iff the token's `sub` is ADMIN_GOOGLE_SUB, else viewer) lives on `request.auth`.
    """

    def authenticate(self, request: Request) -> tuple[User, Principal] | None:
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            claims = id_token.verify_oauth2_token(token, _google_request, audience=settings.GOOGLE_OAUTH_CLIENT_ID)
        except ValueError as e:
            raise AuthenticationFailed(detail={"detail": "Invalid token", "code": "invalid_token"}) from e
        if not claims.get("email_verified"):
            raise AuthenticationFailed(detail={"detail": "Email not verified", "code": "invalid_token"})
        role = "admin" if claims["sub"] == settings.ADMIN_GOOGLE_SUB else "viewer"
        return get_system_user(), Principal(role=role, email=claims.get("email"), sub=claims["sub"])

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"
