from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide

from grow.model.criteria.Criteria import Criteria
from grow.serializer.model.criteria.output.simple import CriteriaSimpleSerializer
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_serializes_side_from_base_criteria_instance(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        child = self.model_fixture_factory.create_genre("Pop Electronic", parent=root, side=CriteriaSide.POP)
        base_instance = Criteria.objects.get(uuid=child.uuid)

        data = CriteriaSimpleSerializer(base_instance).data

        assert data["side"] == CriteriaSide.POP

    def test_serializes_side_as_none_for_tag_from_base_criteria_instance(self):
        tag = self.model_fixture_factory.create_tag("Live")
        base_instance = Criteria.objects.get(uuid=tag.uuid)

        data = CriteriaSimpleSerializer(base_instance).data

        assert data["side"] is None

    def test_serializes_summary_as_none_by_default(self):
        tag = self.model_fixture_factory.create_tag("Live")

        data = CriteriaSimpleSerializer(tag).data

        assert data["summary"] is None

    def test_serializes_summary_for_tag(self):
        tag = self.model_fixture_factory.create_tag("Live", summary="Performed in front of an audience")

        data = CriteriaSimpleSerializer(tag).data

        assert data["summary"] == "Performed in front of an audience"

    def test_serializes_summary_for_genre_from_base_criteria_instance(self):
        genre = self.model_fixture_factory.create_genre("Electronic", summary="Music made with electronic instruments")
        base_instance = Criteria.objects.get(uuid=genre.uuid)

        data = CriteriaSimpleSerializer(base_instance).data

        assert data["summary"] == "Music made with electronic instruments"
