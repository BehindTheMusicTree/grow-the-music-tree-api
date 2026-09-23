from django.conf import settings
from django.contrib.auth.models import User
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from grow.authentication.Principal import Principal
from grow.model.user.get_system_user import get_system_user


class ApiKeyAuthentication(BaseAuthentication):
    """
    Authenticates requests against the static GROW_API_KEY, resolving to grow's
    single system user with the `pipeline` role.
    """

    def authenticate(self, request: Request) -> tuple[User, Principal] | None:
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return None
        if api_key == settings.GROW_API_KEY:
            return get_system_user(), Principal(role="pipeline", email=None, sub=None)
        return None
