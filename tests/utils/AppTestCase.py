from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from tests.utils.AppApiClient import AppApiClient
from tests.utils.ModelFixtureFactory import ModelFixtureFactory


class AppTestCase(TestCase):
    api_client: AppApiClient
    system_user: User
    model_fixture_factory: ModelFixtureFactory

    def setUp(self):
        super().setUp()
        self.system_user = User.objects.get(username=settings.SYSTEM_USERNAME)
        self.model_fixture_factory = ModelFixtureFactory(default_user=self.system_user)
        self.api_client = AppApiClient()
