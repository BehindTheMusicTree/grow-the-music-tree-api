from django.conf import settings
from django.contrib.auth.models import User


def get_prototype_user() -> User:
    return User.objects.get(username=settings.PROTOTYPE_USERNAME)
