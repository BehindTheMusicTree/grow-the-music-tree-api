from grow.model.artist.Artist import Artist
from grow.serializer.model.artist.simple import ArtistSimpleSerializer
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_serializes_artist_with_album(self):
        artist = self.model_fixture_factory.create_artist("Pink Floyd")
        album = self.model_fixture_factory.create_album(name="The Wall")
        album.album_artists.set([artist])

        data = ArtistSimpleSerializer(ArtistSimpleSerializer.setup_queryset(Artist.objects.all()).get()).data

        assert data["name"] == "Pink Floyd"
        assert len(data["albums"]) == 1
        assert data["albums"][0]["name"] == "The Wall"
        assert data["tracks_count"] == 0

    def test_tracks_count_skips_genreless_songs(self):
        artist = self.model_fixture_factory.create_artist("Pink Floyd")
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_song("Money", genre).artists.set([artist])
        self.model_fixture_factory.create_song("Time", None).artists.set([artist])

        data = ArtistSimpleSerializer(ArtistSimpleSerializer.setup_queryset(Artist.objects.all()).get()).data

        assert data["tracks_count"] == 1
