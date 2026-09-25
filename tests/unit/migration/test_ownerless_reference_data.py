from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import User

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from tests.utils.AppTestCase import AppTestCase

make_reference_data_ownerless = import_module(
    "grow.migrations.0024_ownerless_reference_data"
).make_reference_data_ownerless


class TestCase(AppTestCase):
    def test_system_user_rows_become_canonical_and_system_user_is_deleted(self):
        criteria_types = [playlist.type for playlist in CriteriaPlaylist.objects.filter(user=None, criteria=None)]
        CriteriaPlaylist.objects.filter(criteria=None).delete()
        system_user = User.objects.create(username="system")
        other_user = User.objects.create(username="someone")
        for criteria_type in criteria_types:
            CriteriaPlaylist.objects.create(user=system_user, type=criteria_type, criteria=None)
        CriteriaPlaylist.objects.create(user=other_user, type=criteria_types[0], criteria=None)
        self.model_fixture_factory.create_genre(name="Rock", user=system_user)

        make_reference_data_ownerless(apps, None)

        assert not User.objects.filter(username="system").exists()
        assert User.objects.filter(pk=other_user.pk).exists()
        assert Genre.objects.get(name="Rock").user is None
        assert CriteriaPlaylist.objects.filter(user=None, criteria=None).count() == len(criteria_types) == 2
        assert not CriteriaPlaylist.objects.filter(user__isnull=False).exists()
