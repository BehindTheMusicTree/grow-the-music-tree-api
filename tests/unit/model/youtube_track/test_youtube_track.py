from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_relative_url_includes_uuid(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        youtube_track = self.model_fixture_factory.create_youtube_track(title="Track Title", genre=genre)

        assert youtube_track.relative_url == f"library/youtube/{youtube_track.uuid}/"
