from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension, OpenApiSerializerExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import ComponentIdentity
from drf_spectacular.utils import Direction


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


class CriteriaMinimumIdentity(OpenApiSerializerExtension):
    @classmethod
    def _matches(cls, target: Any) -> bool:
        serializer_type = type(target)
        return (
            serializer_type.__module__ == "the_music_tree_genre_kit.serializer.model.criteria.output.minimum"
            and serializer_type.__qualname__ == "build_criteria_minimum_serializer.<locals>.CriteriaMinimumSerializer"
        )

    def get_identity(self, auto_schema: AutoSchema, direction: Direction) -> Any:
        # The factory creates a fresh class per caller with the same UUID and name fields for Criteria and its concrete children.
        return ComponentIdentity(self.map_serializer(auto_schema, direction))

    def map_serializer(self, auto_schema: AutoSchema, direction: Direction) -> dict[str, Any]:
        return auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
