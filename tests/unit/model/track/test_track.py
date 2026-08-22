from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_str_includes_title_and_genre(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        track = self.model_fixture_factory.create_youtube_track(
            title="Plain Track", genre=genre, youtube_video_id="abc123defgh"
        )

        result = str(track)

        assert "Plain Track" in result
        assert "Rock" in result

    def test_simple_str_includes_title_and_no_artists_marker(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        track = self.model_fixture_factory.create_youtube_track(
            title="Plain Track", genre=genre, youtube_video_id="abc123defgh"
        )

        result = track.simple_str()

        assert "Plain Track" in result
        assert "no artists" in result

    def test_simple_str_includes_artist_names(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        artist = self.model_fixture_factory.create_artist("Pink Floyd")
        track = self.model_fixture_factory.create_youtube_track(
            title="Plain Track", genre=genre, youtube_video_id="abc123defgh"
        )
        track.artists.set([artist])

        result = track.simple_str()

        assert "Pink Floyd" in result

    def test_playlists_with_positions_includes_genre_playlist(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        track = self.model_fixture_factory.create_youtube_track(
            title="Track Title", genre=genre, youtube_video_id="abc123defgh"
        )

        positions = track.playlists_with_positions

        assert len(positions) == 1
        assert positions[0][0] == genre.criteria_playlist.uuid
