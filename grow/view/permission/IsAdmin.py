from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from grow.view.permission.IsAdminOrReadOnly import AUTHENTICATION_REQUIRED_DETAIL


def is_admin(request: Request) -> bool:
    return request.auth is not None and request.auth.role == "admin"


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        if request.auth is None:
            raise NotAuthenticated(detail=AUTHENTICATION_REQUIRED_DETAIL)
        return is_admin(request)
