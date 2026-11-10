from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.urls import reverse
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.playlist.Playlist import Playlist
from the_music_tree_genre_kit.track.Track import Track

from grow.genre_music.membership import membership_bucket_counts, stored_membership_bucket_counts
from grow.genre_music.summary import genre_playlist_summaries
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.playlist.GenreMembershipCount import GenreMembershipCount
from tests.utils.AppTestCase import AppTestCase


class TestMembershipProjection(AppTestCase):
    def assert_projection(self):
        assert stored_membership_bucket_counts() == membership_bucket_counts()

    def test_source_changes_and_rollback(self):
        factory = self.model_fixture_factory
        parent = factory.create_genre("Parent")
        child = factory.create_genre("Child", parent=parent)
        song = factory.create_song("Song", genre=child)
        playlist = GenrePlaylist.objects.get(criteria=child)
        relation = TrackPlaylistRel.objects.get(playlist=playlist, track=song)
        owner = User.objects.create(username="private")
        self.assert_projection()
        for genre in (parent.pk, None, child.pk):
            Track.objects.filter(pk=song.pk).update(genre_id=genre)
            self.assert_projection()
        for model, pk in ((Track, song.pk), (Playlist, playlist.pk), (TrackPlaylistRel, relation.pk)):
            for user in (owner, None):
                model.objects.filter(pk=pk).update(user=user)
                self.assert_projection()
        with transaction.atomic():
            Track.objects.filter(pk=song.pk).update(genre=None)
            TrackPlaylistRel.objects.filter(pk=relation.pk).delete()
            self.assert_projection()
            transaction.set_rollback(True)
        self.assert_projection()
        for type_id in (1, 0):
            CriteriaPlaylist.objects.filter(pk=playlist.pk).update(type_id=type_id)
            self.assert_projection()
        song.delete()
        self.assert_projection()
        playlist.delete()
        self.assert_projection()

    def test_bulk_raw_sql_and_verification(self):
        factory = self.model_fixture_factory
        genre = factory.create_genre("Genre")
        song = factory.create_song("Song", genre=genre)
        playlist = GenrePlaylist.objects.get(criteria=genre)
        TrackPlaylistRel.objects.filter(playlist=playlist, track=song).delete()
        TrackPlaylistRel.objects.bulk_create([TrackPlaylistRel(playlist=playlist, track=song, user=None)])
        self.assert_projection()
        quote = connection.ops.quote_name
        table = quote(Track._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET genre_id = NULL WHERE uuid = %s",
                [song.pk.hex if connection.vendor == "sqlite" else song.pk],
            )
        self.assert_projection()
        GenreMembershipCount.objects.filter(playlist=playlist).update(tracks_count=99)
        with self.assertRaises(CommandError):
            call_command("verify_genre_membership_counts", verbosity=0)
        assert GenreMembershipCount.objects.get(playlist=playlist).tracks_count == 99
        call_command("verify_genre_membership_counts", repair=True, verbosity=0)
        self.assert_projection()

    def test_genre_deletion_moves_members_to_genreless_bucket(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        self.model_fixture_factory.create_song("Song", genre=genre)
        Track.objects.filter(genre=genre).update(genre=None)
        genre.delete()
        self.assert_projection()

    def test_summary_endpoints_agree_on_actual_membership_and_catalogue(self):
        parent = self.model_fixture_factory.create_genre("Parent")
        child = self.model_fixture_factory.create_genre("Child", parent=parent)
        song = self.model_fixture_factory.create_song("Song", genre=child)
        playlist = GenrePlaylist.objects.get(criteria=parent)
        TrackPlaylistRel.objects.filter(playlist=playlist, track=song).delete()
        expected = {
            "genreOnlyTracksCount": 0,
            "genreAndSubgenresTracksCount": {"canonical": 0, "regional": 0, "all": 0},
        }
        catalogue = {
            "genreOnlyTracksCount": 0,
            "genreAndSubgenresTracksCount": {"canonical": 1, "regional": 0, "all": 1},
        }
        for route in ("genre-playlist-detail", "playlist-detail"):
            response = self.api_client.get(reverse(route, kwargs={"pk": playlist.pk}))
            assert response.status_code == 200, response.content
            data = response.json()
            assert {key: data[key] for key in expected} == expected
            assert data["tracksCount"] == 0
            assert data["catalogue"] == catalogue
        for route in ("genre-playlist-list", "playlist-list"):
            data = self.api_client.get(reverse(route)).json()["results"]
            row = next(row for row in data if row["uuid"] == str(playlist.pk))
            assert {key: row[key] for key in expected} == expected
            assert row["catalogue"] == catalogue
        tree = self.api_client.get(reverse("genre-playlist-tree"), {"tree_name": "canonical"}).json()
        row = next(row for row in tree if row["uuid"] == str(playlist.pk))
        assert {key: row[key] for key in expected} == expected
        assert row["catalogue"] == catalogue

    def test_repeated_summaries_follow_writes_and_transaction_rollback(self):
        parent = self.model_fixture_factory.create_genre("Parent")
        child = self.model_fixture_factory.create_genre("Child", parent=parent)
        playlist = GenrePlaylist.objects.get(criteria=parent)

        def summary():
            return genre_playlist_summaries({playlist.pk})[playlist.pk]

        assert summary()["catalogue"]["genre_and_subgenres_tracks_count"]["all"] == 0
        song = self.model_fixture_factory.create_song("Song", genre=child)
        assert summary()["catalogue"]["genre_and_subgenres_tracks_count"]["all"] == 1
        assert summary()["tracks_count"] == 1
        with transaction.atomic():
            TrackPlaylistRel.objects.filter(playlist=playlist, track=song).delete()
            assert summary()["tracks_count"] == 0
            assert summary()["catalogue"]["genre_and_subgenres_tracks_count"]["all"] == 1
            transaction.set_rollback(True)
        assert summary()["tracks_count"] == 1
        with transaction.atomic():
            child.parent = None
            child.save()
            assert summary()["catalogue"]["genre_and_subgenres_tracks_count"]["all"] == 0
            transaction.set_rollback(True)
        assert summary()["catalogue"]["genre_and_subgenres_tracks_count"]["all"] == 1
        assert summary()["tracks_count"] == 1

    def test_trigger_migration_can_be_reversed_and_backfilled_again(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        song = self.model_fixture_factory.create_song("Song", genre=genre)
        migration = import_module("grow.migrations.0108_maintain_genre_membership_counts")
        # 0115 puts a trigger on grow_song that uses 0108's gate function, so it must be
        # reversed first and replayed last, as migrate would.
        catalogue = import_module("grow.migrations.0115_maintain_genre_catalogue_counts")
        editor = connection.schema_editor()
        catalogue.drop(apps, editor)
        migration.drop(apps, editor)
        Track.objects.filter(pk=song.pk).update(genre=None)
        assert stored_membership_bucket_counts() != membership_bucket_counts()
        migration.create(apps, editor)
        connection.cursor().execute("DELETE FROM grow_genre_catalogue_count")
        catalogue.create(apps, editor)
        self.assert_projection()
