from django.db import IntegrityError, transaction
from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase

IMAGE = {
    "url": "https://upload.wikimedia.org/edm.jpg",
    "page_url": "https://commons.wikimedia.org/wiki/File:Edm.jpg",
    "author": "Jane",
    "license": "CC BY-SA 4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
}


class TestCase(GenreTestCase):
    def _import(self, image):
        node = {Fields.ID: "Q101", Fields.NAME_PUBLIC: "EDM", Fields.CHILDREN: []}
        if image is not None:
            node["image"] = image
        root = {Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}
        return self._post_genres_tree_import(data={Fields.TREE_NAME: "canonical", Fields.TREE: [root, node]})

    def test_image_is_imported_then_cleared_when_the_node_drops_it(self):
        assert self._import(IMAGE).status_code == status.HTTP_201_CREATED
        genre = Genre.objects.get(wikidata_id="Q101")
        assert (genre.image_url, genre.image_author, genre.image_license) == (
            IMAGE["url"],
            IMAGE["author"],
            IMAGE["license"],
        )

        assert self._import(None).status_code < status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(wikidata_id="Q101").image_url is None

    def test_invalid_image_is_rejected(self):
        response = self._import({**IMAGE, "url": "http://example.com/edm.jpg"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "image" in response.content.decode()
        assert not Genre.objects.filter(wikidata_id="Q101").exists()

    def test_database_refuses_a_partial_image(self):
        genre = self.model_fixture_factory.create_genre("EDM")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Genre.objects.filter(pk=genre.pk).update(image_url="https://upload.wikimedia.org/edm.jpg")
