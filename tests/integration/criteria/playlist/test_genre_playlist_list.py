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

    def test_list_genre_playlists_returns_criteria_summary(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        self.model_fixture_factory.create_genre("EDM", parent=root, summary="Electronic dance music")

        response = self.api_client.get(path=reverse("genre-playlist-list"))

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        edm_result = next(result for result in results if result["criteria"] and result["criteria"]["name"] == "EDM")
        assert edm_result["criteria"]["summary"] == "Electronic dance music"

    def _list_names_by_tree_name(self, tree_name):
        self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_genre("Italian progressive rock", tree_name="regional")

        response = self.api_client.get(path=reverse("genre-playlist-list"), data={"tree_name": tree_name})

        assert response.status_code == status.HTTP_200_OK
        return [result["criteria"] and result["criteria"]["name"] for result in response.json()["results"]]

    def test_list_genre_playlists_filtered_by_canonical_tree_includes_genreless(self):
        assert sorted(self._list_names_by_tree_name("canonical"), key=str) == [None, "Rock"]

    def test_list_genre_playlists_filtered_by_regional_tree_excludes_genreless(self):
        assert self._list_names_by_tree_name("regional") == ["Italian progressive rock"]

    def test_list_genre_playlists_with_bogus_tree_name_then_400(self):
        response = self.api_client.get(path=reverse("genre-playlist-list"), data={"tree_name": "bogus"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_genre_playlists_returns_304_when_etag_matches(self):
        self.model_fixture_factory.create_genre("Electronic")

        first = self.api_client.get(path=reverse("genre-playlist-list"))
        second = self.api_client.get(path=reverse("genre-playlist-list"), HTTP_IF_NONE_MATCH=first["ETag"])

        assert second.status_code == status.HTTP_304_NOT_MODIFIED
