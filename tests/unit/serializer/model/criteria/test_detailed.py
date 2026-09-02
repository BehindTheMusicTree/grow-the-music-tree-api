from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide

from grow.model.criteria.Criteria import Criteria
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

    def test_serializes_side_from_base_criteria_instance(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        child = self.model_fixture_factory.create_genre("Pop Electronic", parent=root, side=CriteriaSide.POP)
        base_instance = Criteria.objects.get(uuid=child.uuid)

        data = CriteriaDetailedSerializer(base_instance).data

        assert data["side"] == CriteriaSide.POP

    def test_serializes_side_as_none_for_tag_from_base_criteria_instance(self):
        tag = self.model_fixture_factory.create_tag("Live")
        base_instance = Criteria.objects.get(uuid=tag.uuid)

        data = CriteriaDetailedSerializer(base_instance).data

        assert data["side"] is None

    def test_serializes_essential_tracks(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        track = self.model_fixture_factory.create_youtube_track("Strobe", genre=genre)
        genre.essential_tracks.add(track)

        data = CriteriaDetailedSerializer(genre).data

        assert [essential_track["uuid"] for essential_track in data["essential_tracks"]] == [str(track.uuid)]

    def test_serializes_essential_tracks_as_empty_list_by_default(self):
        genre = self.model_fixture_factory.create_genre("Rock")

        data = CriteriaDetailedSerializer(genre).data

        assert data["essential_tracks"] == []

    def test_serializes_essential_tracks_as_empty_list_for_tag_from_base_criteria_instance(self):
        tag = self.model_fixture_factory.create_tag("Live")
        base_instance = Criteria.objects.get(uuid=tag.uuid)

        data = CriteriaDetailedSerializer(base_instance).data

        assert data["essential_tracks"] == []
