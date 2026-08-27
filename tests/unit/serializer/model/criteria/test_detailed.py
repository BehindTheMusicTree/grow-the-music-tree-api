from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide

from grow.serializer.model.criteria.output.detailed import CriteriaDetailedSerializer
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_serializes_side(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        child = self.model_fixture_factory.create_genre("Pop Electronic", parent=root, side=CriteriaSide.POP)

        data = CriteriaDetailedSerializer(child).data

        assert data["side"] == CriteriaSide.POP

    def test_serializes_side_as_none_by_default(self):
        root = self.model_fixture_factory.create_genre("Rock")

        data = CriteriaDetailedSerializer(root).data

        assert data["side"] is None
