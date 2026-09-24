from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission

from grow.view.permission.IsAdminOrReadOnly import AUTHENTICATION_REQUIRED_DETAIL


class IsPipelineOrAdmin(BasePermission):
    """For the nightly pipeline's import endpoints: the API key (pipeline role) or an admin token."""

    def has_permission(self, request, view):
        if request.auth is None:
            raise NotAuthenticated(detail=AUTHENTICATION_REQUIRED_DETAIL)
        return request.auth.role in {"admin", "pipeline"}
