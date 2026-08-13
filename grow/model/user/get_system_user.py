from django.conf import settings
from django.contrib.auth.models import User


def get_system_user() -> User:
    return User.objects.get(username=settings.SYSTEM_USERNAME)
