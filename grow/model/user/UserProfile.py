from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Public identity of a `User`: history entries show the actor's pseudo, never their email."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    pseudo = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = "grow_user_profile"

    def __str__(self) -> str:
        return self.pseudo
