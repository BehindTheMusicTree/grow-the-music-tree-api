from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from grow.model.user.UserProfile import UserProfile


class Command(BaseCommand):
    help = "Set the public pseudo shown as actor in history entries for the User with the given email."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("pseudo")

    def handle(self, *args, email: str, pseudo: str, **options) -> None:
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist as e:
            raise CommandError(f"No User with email {email}") from e
        except User.MultipleObjectsReturned as e:
            raise CommandError(f"Several Users with email {email}") from e
        try:
            UserProfile.objects.update_or_create(user=user, defaults={"pseudo": pseudo})
        except IntegrityError as e:
            raise CommandError(f"Pseudo {pseudo} is already taken") from e
        self.stdout.write(f"{email} -> {pseudo}")
