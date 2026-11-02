from rest_framework import status

from grow.curation.rows import InvalidRow, RowConflict, check_edit
from grow.model.curation.CurationEntry import CurationEntry
from tests.integration.criteria.GenreTestCase import GenreTestCase

SPLIT = "LOCAL:split-node"
COMMERCIAL = "Q777001"
UNDERGROUND = "LOCAL:split-underground"


def _main_parent(item_id: str, parent: str) -> dict[str, str]:
    return {"item_id": item_id, "parent_item_id": parent, "exclude_other_parents": "true", "reason": "r"}


def _scene(item_id: str, scene: str) -> dict[str, str]:
    return {"item_id": item_id, "scene": scene, "reason": "r"}


class TestCase(GenreTestCase):
    def setUp(self):
        super().setUp()
        # Scenes first: a node still holding a non-scene child can't become a split.
        for item_id, scene in ((COMMERCIAL, "commercial"), (UNDERGROUND, "underground")):
            CurationEntry.objects.upsert("canonical_genre_scene", _scene(item_id, scene))
        for item_id in (COMMERCIAL, UNDERGROUND):
            CurationEntry.objects.upsert("main_parent", _main_parent(item_id, SPLIT))

    def test_main_parent_directly_under_split_then_invalid_row(self):
        with self.assertRaises(InvalidRow) as raised:
            CurationEntry.objects.upsert("main_parent", _main_parent("Q777002", SPLIT))

        assert "can't be its direct child" in raised.exception.errors["item_id"]

    def test_main_parent_under_a_scene_then_created(self):
        assert CurationEntry.objects.upsert("main_parent", _main_parent("Q777002", COMMERCIAL)) == "created"

    def test_second_scene_node_of_same_scene_then_invalid_row(self):
        CurationEntry.objects.upsert("canonical_genre_scene", _scene("Q777003", "commercial"))

        with self.assertRaises(InvalidRow) as raised:
            CurationEntry.objects.upsert("main_parent", _main_parent("Q777003", SPLIT))

        assert "already has a commercial scene child" in raised.exception.errors["item_id"]

    def test_scene_on_third_child_of_split_then_invalid_row(self):
        CurationEntry.objects.create(
            user=None,
            list_name="main_parent",
            key="Q777004",
            values={"parent_item_id": SPLIT, "exclude_other_parents": True},
            reason="r",
        )

        with self.assertRaises(InvalidRow):
            CurationEntry.objects.upsert("canonical_genre_scene", _scene("Q777004", "commercial"))

    def test_editing_a_scene_node_then_unchanged(self):
        assert CurationEntry.objects.upsert("canonical_genre_scene", _scene(COMMERCIAL, "commercial")) == "unchanged"

    def test_scene_node_swapping_scene_then_row_conflict(self):
        entry = CurationEntry.objects.get(user=None, list_name="canonical_genre_scene", key=COMMERCIAL)

        with self.assertRaises(RowConflict):
            check_edit(
                CurationEntry.objects.filter(user=None),
                "canonical_genre_scene",
                _scene(COMMERCIAL, "underground"),
                entry.pk,
            )

    def test_admin_reparent_onto_split_then_400_and_no_rule(self):
        split = self.model_fixture_factory.create_genre("Split", wikidata_id=SPLIT)
        genre = self.model_fixture_factory.create_genre("Rave", wikidata_id="Q777005")

        response = self._put_genre(genre.uuid, data={"name": "Rave", "parent": str(split.uuid)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not CurationEntry.objects.filter(user=None, list_name="main_parent", key="Q777005").exists()
