from typing import Any

from rest_framework.request import Request
from the_music_tree_api_kit.base.BaseModel import BaseModel
from the_music_tree_api_kit.view.viewset.model.AppModelViewSet import AppModelViewSet

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.authentication.GoogleIdTokenAuthentication import GoogleIdTokenAuthentication
from grow.view.permission.IsAdminOrReadOnly import IsAdminOrReadOnly


class GrowModelViewSet[T: BaseModel](AppModelViewSet[T]):
    authentication_classes = [GoogleIdTokenAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAdminOrReadOnly]

    def get_owner(self, request: Request) -> None:
        # Grow serves the canonical reference dataset: rows have no owner (user IS NULL).
        return None

    def _get_manager_write_kwargs(self, request: Request) -> dict[str, Any]:
        # IsAdminOrReadOnly guarantees request.auth.role == "admin" on every write reaching here.
        return {"actor": request.auth.email}
