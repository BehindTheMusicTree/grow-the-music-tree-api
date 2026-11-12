from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import User

from grow.model.user.UserProfile import UserProfile
from tests.utils.AppTestCase import AppTestCase

migration_module = import_module("grow.migrations.0123_curation_bot_profile")


class TestCase(AppTestCase):
    def _seed(self):
        migration_module.seed_curation_bot_profile(apps, None)

    def test_seed_then_bot_has_profile(self):
        UserProfile.objects.filter(user__username="curation-bot").delete()

        self._seed()

        assert UserProfile.objects.get(user__username="curation-bot").pseudo == "curation-bot"

    def test_seed_twice_then_single_bot_and_profile(self):
        self._seed()
        self._seed()

        assert User.objects.filter(username="curation-bot").count() == 1
        assert UserProfile.objects.filter(user__username="curation-bot").count() == 1

    def test_seed_with_existing_bot_and_custom_pseudo_then_kept(self):
        # Migration 0123 already seeded the bot in the test DB.
        UserProfile.objects.filter(user__username="curation-bot").update(pseudo="Gardener Bot")

        self._seed()

        assert UserProfile.objects.get(user__username="curation-bot").pseudo == "Gardener Bot"

    def test_seed_with_existing_bot_without_profile_then_profile_created(self):
        UserProfile.objects.filter(user__username="curation-bot").delete()
        assert User.objects.filter(username="curation-bot").exists()

        self._seed()

        assert UserProfile.objects.get(user__username="curation-bot").pseudo == "curation-bot"
