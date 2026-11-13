from tests.utils.AppTestCase import AppTestCase
from tests.utils.essential_songs import add_essential_song


class TestCase(AppTestCase):
    def test_essential_songs_is_curated_independently_per_genre(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        child = self.model_fixture_factory.create_genre("EDM", parent=root)
        track = self.model_fixture_factory.create_song("Strobe", genre=child)

        add_essential_song(child, track)

        assert list(root.essential_songs.all()) == []
        assert list(child.essential_songs.all()) == [track]

    def test_essential_songs_not_restricted_to_tracks_tagged_with_this_genre(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        other_genre = self.model_fixture_factory.create_genre("Rock")
        track = self.model_fixture_factory.create_song("Strobe", genre=other_genre)

        add_essential_song(genre, track)

        assert list(genre.essential_songs.all()) == [track]
