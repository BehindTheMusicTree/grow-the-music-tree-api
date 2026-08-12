from django.conf import settings
from django.contrib.auth.models import User
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from grow.model.user.get_system_user import get_system_user


class ApiKeyAuthentication(BaseAuthentication):
    """
    Authenticates requests against a single static GROW_API_KEY, since grow is a
    single-tenant service with no per-user login. On a match, the request is
    authenticated as grow's single user record.
    """

    def authenticate(self, request: Request) -> tuple[User, None] | None:
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != settings.GROW_API_KEY:
            return None
        return get_system_user(), None
