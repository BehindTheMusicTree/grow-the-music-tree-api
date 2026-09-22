from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_essential_tracks_is_curated_independently_per_genre(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        child = self.model_fixture_factory.create_genre("EDM", parent=root)
        track = self.model_fixture_factory.create_youtube_track("Strobe", genre=child)

        child.essential_tracks.add(track)

        assert list(root.essential_tracks.all()) == []
        assert list(child.essential_tracks.all()) == [track]

    def test_essential_tracks_not_restricted_to_tracks_tagged_with_this_genre(self):
        genre = self.model_fixture_factory.create_genre("Electronic")
        other_genre = self.model_fixture_factory.create_genre("Rock")
        track = self.model_fixture_factory.create_youtube_track("Strobe", genre=other_genre)

        genre.essential_tracks.add(track)

        assert list(genre.essential_tracks.all()) == [track]
