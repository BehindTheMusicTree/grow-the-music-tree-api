import hmac

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from grow.authentication.Principal import Principal


class PipelineUser(AnonymousUser):
    # Authenticated but row-less, so api-kit's exception handler reports a denied write as 403, not 401.
    @property
    def is_authenticated(self) -> bool:  # type: ignore[override]
        return True


CURATION_BOT_USERNAME = "curation-bot"


class ApiKeyAuthentication(BaseAuthentication):
    """
    Authenticates requests against two static keys. PIPELINE_API_KEY is the `pipeline` role: a service principal
    with no `User` row. CURATION_API_KEY is the `curator` role: it writes curation history, whose actor is a `User`
    FK, so it resolves to the `curation-bot` user.
    """

    def authenticate(self, request: Request) -> tuple[PipelineUser | User, Principal] | None:
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return None
        if hmac.compare_digest(api_key.encode(), settings.PIPELINE_API_KEY.encode()):
            return PipelineUser(), Principal(role="pipeline", email=None, sub=None)
        if hmac.compare_digest(api_key.encode(), settings.CURATION_API_KEY.encode()):
            bot, _ = User.objects.get_or_create(username=CURATION_BOT_USERNAME)
            return bot, Principal(role="curator", email=None, sub=None)
        return None
