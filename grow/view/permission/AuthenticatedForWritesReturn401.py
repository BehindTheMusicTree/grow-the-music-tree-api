from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import SAFE_METHODS, BasePermission


class AuthenticatedForWritesReturn401(BasePermission):
    """
    Allows unauthenticated access for safe methods (GET/HEAD/OPTIONS).
    For write methods, returns 401 (via NotAuthenticated) when the user is not
    authenticated, instead of DRF's default 403 (PermissionDenied).
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if request.user and request.user.is_authenticated:
            return True
        raise NotAuthenticated(detail={"detail": "Authentication required", "code": "authentication_required"})
