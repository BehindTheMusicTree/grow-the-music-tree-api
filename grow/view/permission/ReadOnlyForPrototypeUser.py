from django.conf import settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission


class ReadOnlyForPrototypeUser(BasePermission):
    """
    Allows all methods for every user except the prototype user, which is
    restricted to safe methods (GET/HEAD/OPTIONS). Returns 403 (via
    PermissionDenied) on a write attempt, since the prototype key genuinely
    authenticates and is simply forbidden from writes.

    Note: the_music_tree_api_kit's custom exception handler always hardcodes
    `details.code` to "permission_denied" for PermissionDenied exceptions, so
    only the message text (not a custom machine-readable code) reaches the
    response body.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if request.user and request.user.is_authenticated and request.user.username == settings.PROTOTYPE_USERNAME:
            raise PermissionDenied(detail={"detail": "The prototype API key is read-only"})
        return True
