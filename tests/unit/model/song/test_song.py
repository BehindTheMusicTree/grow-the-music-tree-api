from django.db.utils import IntegrityError

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_relative_url_includes_uuid(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        song = self.model_fixture_factory.create_song(title="Track Title", genre=genre, youtube_video_id="abc123defgh")

        assert song.relative_url == f"library/songs/{song.uuid}/"

    def test_create_with_null_youtube_video_id(self):
        genre = self.model_fixture_factory.create_genre("Rock")

        track = self.model_fixture_factory.create_song(title="Track Title", genre=genre, youtube_video_id=None)

        assert track.youtube_video_id is None
