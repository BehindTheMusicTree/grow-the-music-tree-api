from django.db.utils import IntegrityError

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_relative_url_includes_uuid(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        youtube_track = self.model_fixture_factory.create_youtube_track(
            title="Track Title", genre=genre, youtube_video_id="abc123defgh"
        )

        assert youtube_track.relative_url == f"library/youtube/{youtube_track.uuid}/"

    def test_create_with_null_youtube_video_id_raises_integrity_error(self):
        genre = self.model_fixture_factory.create_genre("Rock")

        with self.assertRaises(IntegrityError):
            self.model_fixture_factory.create_youtube_track(title="Track Title", genre=genre, youtube_video_id=None)
