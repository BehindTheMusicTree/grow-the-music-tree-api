from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_str_includes_no_artist_marker_when_no_album_artists(self):
        album = self.model_fixture_factory.create_album(name="Solo Album")

        result = str(album)

        assert "Solo Album" in result
        assert "[No Artist]" in result

    def test_str_includes_album_artist_names(self):
        artist = self.model_fixture_factory.create_artist("Pink Floyd")
        album = self.model_fixture_factory.create_album(name="The Wall")
        album.album_artists.set([artist])

        result = str(album)

        assert "Pink Floyd" in result

    def test_str_includes_track_details(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        album = self.model_fixture_factory.create_album(name="The Wall")
        self.model_fixture_factory.create_youtube_track(
            title="Another Brick In The Wall", genre=genre, album=album, track_number=1
        )

        result = str(album)

        assert "Another Brick In The Wall" in result

    def test_tracks_not_archived_sorted_orders_by_track_number(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        album = self.model_fixture_factory.create_album(name="The Wall")
        second_track = self.model_fixture_factory.create_youtube_track(
            title="Second", genre=genre, album=album, track_number=2
        )
        first_track = self.model_fixture_factory.create_youtube_track(
            title="First", genre=genre, album=album, track_number=1
        )

        tracks = list(album.tracks_not_archived_sorted)

        assert [track.uuid for track in tracks] == [first_track.uuid, second_track.uuid]
