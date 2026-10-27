from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission

from grow.view.permission.IsAdminOrReadOnly import AUTHENTICATION_REQUIRED_DETAIL


class IsCuratorOrAdmin(BasePermission):
    """For the curation entries endpoints: the curation API key (curator role) or an admin token."""

    def has_permission(self, request, view):
        if request.auth is None:
            raise NotAuthenticated(detail=AUTHENTICATION_REQUIRED_DETAIL)
        return request.auth.role in {"admin", "curator"}
