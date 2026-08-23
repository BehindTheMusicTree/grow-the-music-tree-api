from grow.model.album.Album import Album
from grow.model.artist.Artist import Artist
from grow.model.track_mixin.Fields import Fields
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_get_artists_list_from_names_after_potential_creation_creates_missing_artists(self):
        artists = Artist.objects.get_artists_list_from_names_after_potential_creation(
            user=self.system_user, artists_names=["Daft Punk"]
        )

        assert len(artists) == 1
        assert artists[0].name == "Daft Punk"
        assert Artist.objects.filter(user=self.system_user, name="Daft Punk").exists()

    def test_get_artists_list_from_names_after_potential_creation_reuses_existing_artist(self):
        existing = self.model_fixture_factory.create_artist("Daft Punk")

        artists = Artist.objects.get_artists_list_from_names_after_potential_creation(
            user=self.system_user, artists_names=["Daft Punk"]
        )

        assert len(artists) == 1
        assert artists[0].uuid == existing.uuid

    def test_get_artists_list_from_names_after_potential_creation_without_names(self):
        artists = Artist.objects.get_artists_list_from_names_after_potential_creation(
            user=self.system_user, artists_names=None
        )

        assert artists == []

    def test_delete_instance_deletes_artist(self):
        artist = self.model_fixture_factory.create_artist("To Delete")

        Artist.objects.delete_instance(artist)

        assert not Artist.objects.filter(uuid=artist.uuid).exists()

    def test_delete_instance_with_albums_and_tracks_deletes_linked_album_and_tracks(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        artist = self.model_fixture_factory.create_artist("Linked Artist")
        album = self.model_fixture_factory.create_album(name="Linked Album")
        album.album_artists.set([artist])
        track = self.model_fixture_factory.create_youtube_track(title="Linked Track", genre=genre)
        track.artists.set([artist])

        Artist.objects.delete_instance_with_albums_and_tracks(artist)

        assert not Artist.objects.filter(uuid=artist.uuid).exists()
        assert not Album.objects.filter(uuid=album.uuid).exists()
        assert not track.__class__.objects.filter(uuid=track.uuid).exists()

    def test_delete_instance_if_nothing_linked_deletes_when_no_albums_or_tracks(self):
        artist = self.model_fixture_factory.create_artist("Unlinked Artist")

        Artist.objects.delete_instance_if_nothing_linked(artist)

        assert not Artist.objects.filter(uuid=artist.uuid).exists()

    def test_delete_instance_if_nothing_linked_keeps_artist_with_album(self):
        artist = self.model_fixture_factory.create_artist("Linked Artist")
        album = self.model_fixture_factory.create_album(name="Linked Album")
        album.album_artists.set([artist])

        Artist.objects.delete_instance_if_nothing_linked(artist)

        assert Artist.objects.filter(uuid=artist.uuid).exists()

    def test_delete_instance_if_nothing_linked_keeps_artist_with_track(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        artist = self.model_fixture_factory.create_artist("Linked Artist")
        track = self.model_fixture_factory.create_youtube_track(title="Linked Track", genre=genre)
        track.artists.set([artist])

        Artist.objects.delete_instance_if_nothing_linked(artist)

        assert Artist.objects.filter(uuid=artist.uuid).exists()

    def test_get_default_ordering(self):
        assert Artist.objects.get_default_ordering() == [Fields.NAME_INTERNAL]
