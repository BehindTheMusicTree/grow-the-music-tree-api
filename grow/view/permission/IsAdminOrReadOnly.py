from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import SAFE_METHODS, BasePermission

AUTHENTICATION_REQUIRED_DETAIL = {"detail": "Authentication required", "code": "authentication_required"}

# "pipeline" keeps full write power until the API key is scoped to the import endpoints.
_WRITE_ROLES = {"admin", "pipeline"}


class IsAdminOrReadOnly(BasePermission):
    """
    Safe methods are public. Writes return 401 (NotAuthenticated) without credentials,
    and 403 for an authenticated principal whose role cannot write.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if request.auth is None:
            raise NotAuthenticated(detail=AUTHENTICATION_REQUIRED_DETAIL)
        return request.auth.role in _WRITE_ROLES
