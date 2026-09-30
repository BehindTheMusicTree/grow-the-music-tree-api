from django.contrib.auth.models import User
from django.test import TestCase

from tests.utils.AppApiClient import AppApiClient
from tests.utils.ModelFixtureFactory import ModelFixtureFactory


class AppTestCase(TestCase):
    api_client: AppApiClient
    admin: User
    model_fixture_factory: ModelFixtureFactory

    def setUp(self):
        super().setUp()
        self.model_fixture_factory = ModelFixtureFactory(default_user=None)
        self.api_client = AppApiClient()
        self.admin = self.api_client.admin
