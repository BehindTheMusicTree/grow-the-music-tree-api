from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from tests.utils.AppApiClient import AppApiClient
from tests.utils.ModelFixtureFactory import ModelFixtureFactory
from tests.utils.PrototypeApiClient import PrototypeApiClient


class AppTestCase(TestCase):
    api_client: AppApiClient
    prototype_api_client: PrototypeApiClient
    system_user: User
    prototype_user: User
    model_fixture_factory: ModelFixtureFactory

    def setUp(self):
        super().setUp()
        self.system_user = User.objects.get(username=settings.SYSTEM_USERNAME)
        self.prototype_user = User.objects.get(username=settings.PROTOTYPE_USERNAME)
        self.model_fixture_factory = ModelFixtureFactory(default_user=self.system_user)
        self.api_client = AppApiClient()
        self.prototype_api_client = PrototypeApiClient()
