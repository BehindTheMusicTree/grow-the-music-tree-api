from typing import Any

from django.conf import settings
from django.http import HttpResponse
from rest_framework.test import APIClient


class PrototypeApiClient(APIClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.credentials(HTTP_X_API_KEY=settings.GROW_PROTOTYPE_API_KEY)

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
