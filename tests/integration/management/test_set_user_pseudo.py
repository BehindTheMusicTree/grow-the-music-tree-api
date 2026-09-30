import pytest
from django.core.management import CommandError, call_command

from grow.model.user.UserProfile import UserProfile
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_sets_then_updates_pseudo_of_user_with_email(self):
        call_command("set_user_pseudo", self.admin.email, "Gardener")
        assert UserProfile.objects.get(user=self.admin).pseudo == "Gardener"

        call_command("set_user_pseudo", self.admin.email, "Arborist")
        assert UserProfile.objects.get(user=self.admin).pseudo == "Arborist"

    def test_unknown_email_raises_command_error(self):
        with pytest.raises(CommandError, match=r"ghost@example\.com"):
            call_command("set_user_pseudo", "ghost@example.com", "Ghost")
