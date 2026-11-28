from datetime import UTC, datetime
from uuid import UUID

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.history.HistoryEntry import HistoryEntry
from tests.integration.criteria.GenreTestCase import GenreTestCase
from tests.utils.AppApiClient import ADMIN_PSEUDO
from tests.utils.openapi import assert_response_matches_schema, wire_fixture


class TestCase(GenreTestCase):
    def test_history_returns_entries_newest_first_with_actor_pseudo_and_no_email(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        genre = self.model_fixture_factory.create_genre("Techno")
        Genre.objects.update_instance(genre, parent=root, actor=self.admin)

        response = self.api_client.get(path=reverse("genre-detail", kwargs={"pk": genre.uuid}) + "history/")

        assert response.status_code == status.HTTP_200_OK
        assert [entry["action"] for entry in response.data] == ["parent_changed", "created"]
        assert response.data[0]["actor_pseudo"] == ADMIN_PSEUDO
        assert response.data[0]["new_value"] == "Electronic"
        assert response.data[1]["actor_pseudo"] is None
        assert not any("email" in key.lower() for entry in response.json() for key in entry)
        assert set(response.json()[0]) == {"uuid", "action", "actorPseudo", "oldValue", "newValue", "createdOn"}

    def test_history_fixture_matches_public_response(self):
        genre = self.model_fixture_factory.create_genre("Example")
        HistoryEntry.objects.filter(content_uuid=genre.uuid).update(
            uuid=UUID("00000000-0000-4000-8000-000000000001"),
            created_on=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        with timezone.override(UTC):
            response = self.api_client.get(reverse("genre-detail", kwargs={"pk": genre.uuid}) + "history/")

        assert response.status_code == status.HTTP_200_OK
        assert assert_response_matches_schema(response, "/v1/genres/{uuid}/history/") == wire_fixture("genre-history")
