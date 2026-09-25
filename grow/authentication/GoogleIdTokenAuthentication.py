import cachecontrol
import requests
from django.conf import settings
from django.contrib.auth.models import User
from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import APIException, AuthenticationFailed
from rest_framework.request import Request
from the_music_tree_api_kit.view.error.ApiErrorCode import ApiErrorCodeNumeric
from the_music_tree_api_kit.view.error.ErrorResponse import ErrorResponse

from grow.authentication.Principal import Principal

# CacheControl honors the certs endpoint's Cache-Control max-age, so Google's signing certs aren't refetched per request.
_google_request = GoogleRequest(session=cachecontrol.CacheControl(requests.Session()))


class AuthProviderUnavailable(APIException):
    status_code = 503
    default_detail = "Google sign-in is temporarily unavailable"
    default_code = "auth_provider_unavailable"


ErrorResponse.register_handler(
    AuthProviderUnavailable,
    lambda exc: ErrorResponse.create_error_response(
        error_detail={"message": exc.default_detail, "code": exc.default_code},
        api_error_code=ApiErrorCodeNumeric.EXTERNAL_SERVICE_UNAVAILABLE,
    ),
)


class GoogleIdTokenAuthentication(BaseAuthentication):
    """
    Verifies a Google ID token from `Authorization: Bearer <token>`. Each Google account maps to a `User`
    keyed by its `sub`; the role (admin iff the token's `sub` is ADMIN_GOOGLE_SUB, else viewer) lives on `request.auth`.
    """

    def authenticate(self, request: Request) -> tuple[User, Principal] | None:
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            claims = id_token.verify_oauth2_token(token, _google_request, audience=settings.GOOGLE_OAUTH_CLIENT_ID)
        except TransportError as e:
            raise AuthProviderUnavailable from e
        except ValueError as e:
            raise AuthenticationFailed(detail={"detail": "Invalid token", "code": "invalid_token"}) from e
        if not claims.get("email_verified"):
            raise AuthenticationFailed(detail={"detail": "Email not verified", "code": "invalid_token"})
        role = "admin" if claims["sub"] == settings.ADMIN_GOOGLE_SUB else "viewer"
        user, _ = User.objects.get_or_create(username=claims["sub"], defaults={"email": claims.get("email", "")})
        return user, Principal(role=role, email=claims.get("email"), sub=claims["sub"])

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"
