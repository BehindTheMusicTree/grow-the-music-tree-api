from importlib import import_module
from types import SimpleNamespace

from django.db import connection
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.track.Track import Track

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppTestCase import AppTestCase


class TestRelGenreDenormalization(AppTestCase):
    def assert_in_sync(self):
        stale = [
            rel.pk for rel in TrackPlaylistRel.objects.select_related("track") if rel.genre_id != rel.track.genre_id
        ]
        assert stale == []

    def test_membership_insert_copies_track_genre(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        song = self.model_fixture_factory.create_song("Song", genre=genre)
        playlist = GenrePlaylist.objects.get(criteria=genre)
        assert TrackPlaylistRel.objects.get(playlist=playlist, track=song).genre_id == genre.pk
        TrackPlaylistRel.objects.filter(playlist=playlist, track=song).delete()
        TrackPlaylistRel.objects.bulk_create([TrackPlaylistRel(playlist=playlist, track=song, user=None)])
        self.assert_in_sync()
        assert TrackPlaylistRel.objects.get(playlist=playlist, track=song).genre_id == genre.pk

    def test_track_genre_change_updates_memberships(self):
        factory = self.model_fixture_factory
        parent = factory.create_genre("Parent")
        child = factory.create_genre("Child", parent=parent)
        song = factory.create_song("Song", genre=child)
        for genre in (parent.pk, None, child.pk):
            Track.objects.filter(pk=song.pk).update(genre_id=genre)
            self.assert_in_sync()
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {connection.ops.quote_name(Track._meta.db_table)} SET genre_id = %s WHERE uuid = %s",
                [
                    parent.pk.hex if connection.vendor == "sqlite" else parent.pk,
                    song.pk.hex if connection.vendor == "sqlite" else song.pk,
                ],
            )
        self.assert_in_sync()
        assert TrackPlaylistRel.objects.filter(track=song).exclude(genre_id=parent.pk).count() == 0

    def test_backfill_fills_null_genres(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        song = self.model_fixture_factory.create_song("Song", genre=genre)
        rel = TrackPlaylistRel.objects.get(track=song, playlist=GenrePlaylist.objects.get(criteria=genre))
        TrackPlaylistRel.objects.filter(pk=rel.pk).update(genre=None)
        assert TrackPlaylistRel.objects.get(pk=rel.pk).genre_id is None
        migration = import_module("grow.migrations.0118_maintain_track_playlist_rel_genre")
        # SQLite's schema editor refuses to run inside the test transaction; the migration only needs these two members.
        editor = SimpleNamespace(connection=connection, execute=lambda sql: connection.cursor().execute(sql))
        migration.forwards(None, editor)
        self.assert_in_sync()
