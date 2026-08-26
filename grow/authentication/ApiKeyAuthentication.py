from django.conf import settings
from django.contrib.auth.models import User
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from grow.model.user.get_prototype_user import get_prototype_user
from grow.model.user.get_system_user import get_system_user


class ApiKeyAuthentication(BaseAuthentication):
    """
    Authenticates requests against one of two static keys: GROW_API_KEY (grow's
    single system user, full access) or GROW_PROTOTYPE_API_KEY (a second static
    user with read-only access enforced by ReadOnlyForPrototypeUser). grow is a
    single-tenant service with no per-user login.
    """

    def authenticate(self, request: Request) -> tuple[User, None] | None:
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return None
        if api_key == settings.GROW_API_KEY:
            return get_system_user(), None
        if api_key == settings.GROW_PROTOTYPE_API_KEY:
            return get_prototype_user(), None
        return None
