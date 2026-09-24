from django.urls import reverse
from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def test_history_returns_entries_ordered_oldest_first(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        genre = self.model_fixture_factory.create_genre("Techno")
        Genre.objects.update_instance(genre, parent=root, actor="admin@example.com")

        response = self.api_client.get(path=reverse("genre-detail", kwargs={"pk": genre.uuid}) + "history/")

        assert response.status_code == status.HTTP_200_OK
        actions = [entry["action"] for entry in response.data]
        assert actions == ["created", "parent_changed"]
        assert response.data[1]["actor_email"] == "admin@example.com"
        assert response.data[1]["new_value"] == "Electronic"
