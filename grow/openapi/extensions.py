from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.openapi import AutoSchema


class GoogleIdTokenAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "grow.authentication.GoogleIdTokenAuthentication.GoogleIdTokenAuthentication"
    name = "googleIdToken"

    def get_security_definition(self, auto_schema: AutoSchema) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Google ID token, sent as `Authorization: Bearer <token>`.",
        }


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "grow.authentication.ApiKeyAuthentication.ApiKeyAuthentication"
    name = "apiKey"

    def get_security_definition(self, auto_schema: AutoSchema) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Pipeline or curation key, held server-side.",
        }
