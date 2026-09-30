from importlib import import_module

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from grow.model.criteria.children.genre.Genre import Genre
from tests.utils.AppTestCase import AppTestCase

migration_module = import_module("grow.migrations.0032_historyentry_actor")


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        # Recreates the mid-migration schema/state: `actor` added, `actor_email` not yet removed.
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE grow_history_entry ADD COLUMN actor_email varchar(255) NULL")
        state = MigrationLoader(connection).project_state(("grow", "0031_userprofile"))
        migration_module.Migration.operations[0].state_forwards("grow", state)
        self.apps = state.apps
        self.genre = self.model_fixture_factory.create_genre("Electronic")
        self.HistoryEntry = self.apps.get_model("grow", "HistoryEntry")
        self.HistoryEntry.objects.all().delete()

    def _create_entry(self, actor_email: str | None):
        return self.HistoryEntry.objects.create(
            content_type_id=ContentType.objects.get_for_model(Genre).pk,
            content_uuid=self.genre.uuid,
            action="created",
            actor_email=actor_email,
        )

    def test_actor_emails_are_mapped_to_matching_users_and_pipeline_entries_stay_null(self):
        admin_entry = self._create_entry(self.admin.email)
        pipeline_entry = self._create_entry(None)

        migration_module.map_actor_emails_to_users(self.apps, None)

        admin_entry.refresh_from_db()
        pipeline_entry.refresh_from_db()
        assert admin_entry.actor_id == self.admin.pk
        assert pipeline_entry.actor_id is None

    def test_unmatched_actor_email_raises(self):
        self._create_entry("ghost@example.com")

        with pytest.raises(RuntimeError, match=r"ghost@example\.com"):
            migration_module.map_actor_emails_to_users(self.apps, None)
