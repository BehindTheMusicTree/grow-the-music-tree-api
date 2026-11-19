import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from grow.artist_song.rebuild import rebuild_artist_song
from grow.model.album.Album import Album
from grow.model.artist.Artist import Artist
from grow.model.artist_song.ArtistSong import ArtistSong
from grow.model.artist_song.ArtistSongState import ArtistSongState
from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase

NO_DRIFT = {"missing": 0, "orphaned": 0, "stale": 0}


@pytest.mark.postgres
class TestArtistSongProjection(AppTestCase):
    def setUp(self):
        super().setUp()
        self.factory = self.model_fixture_factory
        self.genre = self.factory.create_genre("Rock")

    def song(self, title: str, *artists: Artist, **kwargs) -> Song:
        song = self.factory.create_song(title, self.genre, **kwargs)
        for artist in artists:
            song.artists.add(artist)
        return song

    def rows(self):
        return set(ArtistSong.objects.values_list("artist_id", "song_id", "title", "album_year"))

    def test_rebuild_fills_swaps_and_marks_ready(self):
        handel = self.factory.create_artist("Handel")
        song = self.song("Messiah", handel)
        assert not ArtistSongState.load().ready

        assert rebuild_artist_song() == 1
        assert rebuild_artist_song() == 1

        state = ArtistSongState.load()
        assert state.ready and state.rebuilt_on is not None
        assert self.rows() == {(handel.pk, song.pk, "Messiah", None)}
        assert ArtistSong.objects.drift() == NO_DRIFT

    def test_rebuild_only_if_not_ready_is_a_noop_once_built(self):
        assert rebuild_artist_song(only_if_not_ready=True) == 0
        assert rebuild_artist_song(only_if_not_ready=True) is None

    def test_orm_writes_keep_projection_in_sync(self):
        handel = self.factory.create_artist("Handel")
        bach = self.factory.create_artist("Bach")
        song = self.song("Messiah", handel)
        rebuild_artist_song()
        created = self.song("Fugue", bach)

        Song.objects.update_instance(song, title="Messiah II")

        assert ArtistSong.objects.filter(song_id=created.pk, artist_id=bach.pk).exists()
        assert ArtistSong.objects.get(song_id=song.pk, artist_id=handel.pk).title == "Messiah II"
        assert ArtistSong.objects.drift() == NO_DRIFT

    def test_song_and_artist_deletion_cascade(self):
        handel = self.factory.create_artist("Handel")
        gone = self.song("Gone", handel)
        kept = self.song("Kept", handel)
        rebuild_artist_song()

        gone.delete()
        assert set(ArtistSong.objects.values_list("song_id", flat=True)) == {kept.pk}
        handel.delete()
        assert not ArtistSong.objects.exists()
        assert ArtistSong.objects.drift() == NO_DRIFT

    def test_album_year_change_follows_the_album(self):
        handel = self.factory.create_artist("Handel")
        album = self.factory.create_album("Water Music", year="1717")
        song = self.song("Alla Hornpipe", handel, album=album)
        rebuild_artist_song()
        assert ArtistSong.objects.get(song_id=song.pk).album_year == 1717

        Album.objects.update_instance(album, year="1720")

        assert ArtistSong.objects.get(song_id=song.pk).album_year == 1720
        assert ArtistSong.objects.drift() == NO_DRIFT

    def test_check_command_reports_drift(self):
        handel = self.factory.create_artist("Handel")
        song = self.song("Messiah", handel)
        call_command("rebuild_artist_song")
        call_command("rebuild_artist_song", "--check")

        with connection.cursor() as cursor:
            cursor.execute("UPDATE grow_artist_song SET title = 'x' WHERE song_id = %s", [song.pk])
        with pytest.raises(CommandError):
            call_command("rebuild_artist_song", "--check")
