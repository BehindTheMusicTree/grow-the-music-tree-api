from the_music_tree_genre_kit.track_mixin.Fields import Fields

from grow.model.album.Album import Album
from grow.model.artist.Artist import Artist
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_create_instance_with_album_artists_list_sets_album_artists(self):
        artist = self.model_fixture_factory.create_artist("Pink Floyd")

        album = Album.objects.create_instance_with_album_artists_list(
            user=self.system_user, name="The Wall", album_artists_list=[artist]
        )

        assert album.name == "The Wall"
        assert list(album.album_artists.all()) == [artist]

    def test_create_instance_with_album_artists_list_without_artists(self):
        album = Album.objects.create_instance_with_album_artists_list(
            user=self.system_user, name="No Artist Album", album_artists_list=[]
        )

        assert album.name == "No Artist Album"
        assert list(album.album_artists.all()) == []

    def test_get_instance_from_name_and_artists_after_potential_creations_creates_when_missing(self):
        artist = self.model_fixture_factory.create_artist("Daft Punk")

        album = Album.objects._get_instance_from_name_and_artists_after_potential_creations(
            user=self.system_user, name="Discovery", album_artists=[artist]
        )

        assert album is not None
        assert album.name == "Discovery"
        assert list(album.album_artists.all()) == [artist]

    def test_get_instance_from_name_and_artists_after_potential_creations_returns_existing(self):
        artist = self.model_fixture_factory.create_artist("Daft Punk")
        existing_album = Album.objects.create_instance_with_album_artists_list(
            user=self.system_user, name="Discovery", album_artists_list=[artist]
        )

        album = Album.objects._get_instance_from_name_and_artists_after_potential_creations(
            user=self.system_user, name="Discovery", album_artists=[artist]
        )

        assert album is not None
        assert album.uuid == existing_album.uuid
        assert Album.objects.filter(user=self.system_user, name="Discovery").count() == 1

    def test_get_instance_from_name_and_artists_after_potential_creations_without_artists(self):
        album = Album.objects._get_instance_from_name_and_artists_after_potential_creations(
            user=self.system_user, name="Compilation", album_artists=[]
        )

        assert album is not None
        assert album.name == "Compilation"
        assert list(album.album_artists.all()) == []

    def test_get_album_from_name_and_album_artists_names_after_potential_creations_creates_artists(self):
        album = Album.objects.get_album_from_name_and_album_artists_names_after_potential_creations(
            user=self.system_user, name="Random Access Memories", album_artists_names=["Daft Punk"]
        )

        assert album is not None
        assert album.name == "Random Access Memories"
        assert Artist.objects.filter(user=self.system_user, name="Daft Punk").exists()

    def test_get_album_from_name_and_album_artists_names_after_potential_creations_without_names(self):
        album = Album.objects.get_album_from_name_and_album_artists_names_after_potential_creations(
            user=self.system_user, name="No Artist Album", album_artists_names=[]
        )

        assert album is not None
        assert list(album.album_artists.all()) == []

    def test_delete_instance_deletes_album(self):
        album = self.model_fixture_factory.create_album(name="To Delete")
        album_uuid = album.uuid

        Album.objects.delete_instance(album)

        assert not Album.objects.filter(uuid=album_uuid).exists()

    def test_delete_instance_with_tracks_and_potentially_artists_deletes_tracks_and_unlinked_artists(self):
        artist = self.model_fixture_factory.create_artist("Solo Artist")
        genre = self.model_fixture_factory.create_genre("Rock")
        album = self.model_fixture_factory.create_album(name="Album With Track")
        track = self.model_fixture_factory.create_youtube_track(title="Track One", genre=genre, album=album)
        track.artists.set([artist])

        Album.objects.delete_instance_with_tracks_and_potentially_artists(album)

        assert not Album.objects.filter(uuid=album.uuid).exists()
        assert not track.__class__.objects.filter(uuid=track.uuid).exists()
        assert not Artist.objects.filter(uuid=artist.uuid).exists()

    def test_delete_instance_with_tracks_and_potentially_artists_keeps_artist_linked_elsewhere(self):
        artist = self.model_fixture_factory.create_artist("Shared Artist")
        genre = self.model_fixture_factory.create_genre("Rock")
        album = self.model_fixture_factory.create_album(name="Album With Track")
        other_album = self.model_fixture_factory.create_album(name="Other Album")
        other_album.album_artists.set([artist])
        track = self.model_fixture_factory.create_youtube_track(title="Track One", genre=genre, album=album)
        track.artists.set([artist])

        Album.objects.delete_instance_with_tracks_and_potentially_artists(album)

        assert Artist.objects.filter(uuid=artist.uuid).exists()

    def test_delete_instance_if_no_track_linked_with_potential_album_artist_deletion_deletes_album(self):
        artist = self.model_fixture_factory.create_artist("Lonely Artist")
        album = self.model_fixture_factory.create_album(name="Trackless Album")
        album.album_artists.set([artist])

        Album.objects.delete_instance_if_no_track_linked_with_potential_album_artist_deletion(album)

        assert not Album.objects.filter(uuid=album.uuid).exists()
        assert not Artist.objects.filter(uuid=artist.uuid).exists()

    def test_delete_instance_if_no_track_linked_with_potential_album_artist_deletion_keeps_album_with_tracks(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        album = self.model_fixture_factory.create_album(name="Album With Track")
        self.model_fixture_factory.create_youtube_track(title="Track One", genre=genre, album=album)

        Album.objects.delete_instance_if_no_track_linked_with_potential_album_artist_deletion(album)

        assert Album.objects.filter(uuid=album.uuid).exists()

    def test_get_default_ordering(self):
        assert Album.objects.get_default_ordering() == [Fields.NAME_INTERNAL]
