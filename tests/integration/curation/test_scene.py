from django.urls import reverse

from grow.curation.rows import InvalidRow
from grow.model.curation.CurationEntry import CurationEntry
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def _scene_row(self, scene: str) -> dict[str, str]:
        return {"item_id": "Q404", "scene": scene, "reason": "r"}

    def test_scene_entry_with_valid_value_then_created(self):
        assert CurationEntry.objects.upsert("canonical_genre_scene", self._scene_row("commercial")) == "created"

    def test_scene_entry_with_unknown_value_then_invalid_row(self):
        with self.assertRaises(InvalidRow):
            CurationEntry.objects.upsert("canonical_genre_scene", self._scene_row("mainstream"))

    def test_genre_playlist_list_then_scene_on_marked_genre_only(self):
        self.model_fixture_factory.create_genre("Edm", wikidata_id="Q851213", scene="commercial")
        self.model_fixture_factory.create_genre("Techno", wikidata_id="Q9")

        results = self.api_client.get(path=reverse("genre-playlist-list")).json()["results"]

        scenes = {r["name"]: r["scene"] for r in results}

        assert scenes["Edm"] == "commercial"
        assert scenes["Techno"] is None

    def test_genre_list_filtered_by_scene(self):
        edm = self.model_fixture_factory.create_genre("Edm", wikidata_id="Q851213", scene="commercial")
        self.model_fixture_factory.create_genre("Techno", wikidata_id="Q9")

        response = self.api_client.get(path=reverse("genre-list"), data={"scene": "commercial"})

        body = response.json()
        assert [r["uuid"] for r in body["results"]] == [str(edm.uuid)]
        assert body["results"][0]["scene"] == "commercial"
