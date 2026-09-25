import hmac

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from grow.authentication.Principal import Principal


class PipelineUser(AnonymousUser):
    # Authenticated but row-less, so api-kit's exception handler reports a denied write as 403, not 401.
    @property
    def is_authenticated(self) -> bool:  # type: ignore[override]
        return True


class ApiKeyAuthentication(BaseAuthentication):
    """
    Authenticates requests against the static PIPELINE_API_KEY as the `pipeline` role. The pipeline is a
    service principal, not a user: it has no `User` row.
    """

    def authenticate(self, request: Request) -> tuple[PipelineUser, Principal] | None:
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return None
        if hmac.compare_digest(api_key.encode(), settings.PIPELINE_API_KEY.encode()):
            return PipelineUser(), Principal(role="pipeline", email=None, sub=None)
        return None
