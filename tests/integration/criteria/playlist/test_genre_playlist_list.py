from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_list_genre_playlists_returns_criteria_side(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        self.model_fixture_factory.create_genre("EDM", parent=root, side=CriteriaSide.POP)

        response = self.api_client.get(path=reverse("genre-playlist-list"))

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        edm_result = next(result for result in results if result["criteria"] and result["criteria"]["name"] == "EDM")
        assert edm_result["criteria"]["side"] == CriteriaSide.POP
