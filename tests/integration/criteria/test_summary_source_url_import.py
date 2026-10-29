from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.Fields import Fields as CriteriaFields
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def _import_node_with_source_url(self, source_url):
        node = {
            Fields.ID: "Q101",
            Fields.NAME_PUBLIC: "EDM",
            CriteriaFields.SUMMARY: "Loud.",
            CriteriaFields.SUMMARY_SOURCE_URL: source_url,
            Fields.CHILDREN: [],
        }
        root = {Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}
        return self._post_genres_tree_import(data={Fields.TREE_NAME: "canonical", Fields.TREE: [root, node]})

    def test_non_http_summary_source_url_is_rejected(self):
        response = self._import_node_with_source_url("ftp://example.com/edm")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "summarySourceUrl" in response.content.decode()
        assert not Genre.objects.filter(wikidata_id="Q101").exists()

    def test_https_summary_source_url_is_imported(self):
        response = self._import_node_with_source_url("https://en.wikipedia.org/wiki/EDM")

        assert response.status_code == status.HTTP_201_CREATED
        assert Genre.objects.get(wikidata_id="Q101").summary_source_url == "https://en.wikipedia.org/wiki/EDM"
