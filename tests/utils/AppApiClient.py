from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpResponse
from rest_framework.test import APIClient

from grow.authentication.Principal import Principal
from grow.model.user.UserProfile import UserProfile

ADMIN_EMAIL = "admin@example.com"
ADMIN_PSEUDO = "admin"


class AppApiClient(APIClient):
    admin: User

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin, _ = User.objects.get_or_create(username=settings.ADMIN_GOOGLE_SUB, defaults={"email": ADMIN_EMAIL})
        UserProfile.objects.get_or_create(user=self.admin, defaults={"pseudo": ADMIN_PSEUDO})
        self.force_authenticate(
            user=self.admin,
            token=Principal(role="admin", email=ADMIN_EMAIL, sub=settings.ADMIN_GOOGLE_SUB),
        )

    def credentials(self, **kwargs):
        # Explicit credentials opt out of the default forced admin, so the real authenticators run.
        # Cleared on the handler directly: force_authenticate(None) calls logout(), which needs sessions.
        self.handler._force_user = None
        self.handler._force_token = None
        super().credentials(**kwargs)

    def _handle_response(self, response: HttpResponse, handle_response=None) -> HttpResponse:
        if handle_response:
            handle_response(response)
        return response

    def get(self, path, data: dict | None = None, follow=False, **extra) -> HttpResponse:
        handle_response = extra.pop("handle_response", None)
        response = super().get(path, data, follow, **extra)
        return self._handle_response(response, handle_response)

    def post(self, path, data: Any = None, format="json", follow=False, **extra) -> HttpResponse:
        handle_response = extra.pop("handle_response", None)
        response = super().post(path, data, format=format, follow=follow, **extra)
        return self._handle_response(response, handle_response)

    def put(self, path, data: Any = None, format="json", follow=False, **extra) -> HttpResponse:
        handle_response = extra.pop("handle_response", None)
        response = super().put(path, data, format=format, follow=follow, **extra)
        return self._handle_response(response, handle_response)

    def delete(self, path, data: Any = None, format="json", follow=False, **extra) -> HttpResponse:
        handle_response = extra.pop("handle_response", None)
        response = super().delete(path, data, format=format, follow=follow, **extra)
        return self._handle_response(response, handle_response)
