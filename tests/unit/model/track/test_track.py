from grow.model.track.Track import Track
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_resolve_concrete_with_youtube_track_then_returns_youtube_track(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        youtube_track = self.model_fixture_factory.create_youtube_track(
            title="Track Title", genre=genre, youtube_video_id="abc123defgh"
        )

        base_track = Track.objects.get(uuid=youtube_track.uuid)

        assert base_track.resolve_concrete() == youtube_track

    def test_resolve_concrete_with_plain_track_then_returns_self(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        track = Track.objects.create(user=self.system_user, title="Plain Track", genre=genre)

        assert track.resolve_concrete() == track

    def test_str_includes_title_and_genre(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        track = Track.objects.create(user=self.system_user, title="Plain Track", genre=genre)

        result = str(track)

        assert "Plain Track" in result
        assert "Rock" in result

    def test_simple_str_includes_title_and_no_artists_marker(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        track = Track.objects.create(user=self.system_user, title="Plain Track", genre=genre)

        result = track.simple_str()

        assert "Plain Track" in result
        assert "no artists" in result

    def test_simple_str_includes_artist_names(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        artist = self.model_fixture_factory.create_artist("Pink Floyd")
        track = Track.objects.create(user=self.system_user, title="Plain Track", genre=genre, artists=[artist])

        result = track.simple_str()

        assert "Pink Floyd" in result

    def test_playlists_with_positions_includes_genre_playlist(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        track = Track.objects.create(user=self.system_user, title="Plain Track", genre=genre)

        positions = track.playlists_with_positions

        assert len(positions) == 1
        assert positions[0][0] == genre.criteria_playlist.uuid
