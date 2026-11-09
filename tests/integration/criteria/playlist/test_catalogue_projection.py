from importlib import import_module
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, IntegrityError, connection, transaction
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.track.AbstractTrackManager import AbstractTrackManager
from the_music_tree_genre_kit.track.Track import Track

from grow.genre_music.catalogue_verification import (
    _compare,
    catalogue_bucket_counts,
    stored_catalogue_bucket_counts,
    verify_catalogue_counts,
)
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.playlist.GenreCatalogueCount import GenreCatalogueCount
from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase


class TestCatalogueProjection(AppTestCase):
    def assert_projection(self):
        assert stored_catalogue_bucket_counts() == catalogue_bucket_counts()

    def test_pre_gate_manager_lifecycle_does_not_double_count(self):
        a, b = [self.model_fixture_factory.create_genre(name) for name in ("A", "B")]
        song = self.model_fixture_factory.create_song("Song", genre=a)
        assert all(report.valid for report in verify_catalogue_counts().values())
        # Before this change, update/delete inherited these kit methods directly.
        # Exercise that path against the new schema, bypassing the new wrappers.
        AbstractTrackManager.update_instance(Song.objects, song, genre=b)
        assert all(report.valid for report in verify_catalogue_counts().values())
        AbstractTrackManager.delete_instance(Song.objects, song)
        assert all(report.valid for report in verify_catalogue_counts().values())

    def test_save_queryset_bulk_update_ownership_and_rollback(self):
        factory = self.model_fixture_factory
        a, b = factory.create_genre("A"), factory.create_genre("B")
        owner = User.objects.create(username="private")
        songs = [factory.create_song(str(i), genre=a, youtube_video_id=None) for i in range(3)]
        for genre in (b, None, a):
            songs[0].genre = genre
            songs[0].save(update_fields=["genre"])
            self.assert_projection()
        Track.objects.filter(pk__in=[song.pk for song in songs]).update(genre=b)
        self.assert_projection()
        for song in songs:
            song.genre = None
        Song.objects.bulk_update(songs, ["genre"])
        self.assert_projection()
        for user in (owner, None):
            Track.objects.filter(pk=songs[0].pk).update(user=user)
            self.assert_projection()
        for rollback in (True, False):
            with transaction.atomic():
                Track.objects.filter(pk=songs[0].pk).update(genre=a)
                Song.objects.filter(pk=songs[1].pk).delete()
                self.assert_projection()
                transaction.set_rollback(rollback)
            self.assert_projection()

    def test_parent_without_child_and_raw_child_lifecycle(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        song = self.model_fixture_factory.create_song("Song", genre=genre)
        quote = connection.ops.quote_name
        pk = song.pk.hex if connection.vendor == "sqlite" else song.pk
        # keep_parents exercises Django's actual child-only collector order.
        song.delete(keep_parents=True)
        assert Track.objects.filter(pk=pk).exists()
        assert catalogue_bucket_counts() == {}
        self.assert_projection()
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {quote(Song._meta.db_table)} (track_id, is_manually_edited) VALUES (%s, false)", [pk]
            )
        self.assert_projection()
        assert catalogue_bucket_counts() == {genre.pk: 1}
        with connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {quote(Song._meta.db_table)} WHERE track_id = %s", [pk])
        self.assert_projection()
        Track.objects.filter(pk=pk).delete()
        self.assert_projection()

    def test_child_only_delete_exposes_legacy_drift_without_repair(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        song = self.model_fixture_factory.create_song("Song", genre=genre)
        song.delete(keep_parents=True)
        reports = verify_catalogue_counts()
        assert reports["shadow"].valid
        assert reports["legacy"].mismatches[genre.pk] == (0, 1)

    def test_owner_change_exposes_legacy_drift_without_repair(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        song = self.model_fixture_factory.create_song("Song", genre=genre)
        owner = User.objects.create(username="private")
        Track.objects.filter(pk=song.pk).update(user=owner)
        reports = verify_catalogue_counts()
        assert reports["shadow"].valid
        assert reports["legacy"].mismatches[genre.pk] == (0, 1)

    def test_raw_genre_change_exposes_legacy_drift_without_repair(self):
        a, b = [self.model_fixture_factory.create_genre(name) for name in ("A", "B")]
        song = self.model_fixture_factory.create_song("Song", genre=a)

        def encode(pk):
            return pk.hex if connection.vendor == "sqlite" else pk

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE the_music_tree_genre_kit_track SET genre_id = %s WHERE uuid = %s",
                [encode(b.pk), encode(song.pk)],
            )
        reports = verify_catalogue_counts()
        assert reports["shadow"].valid
        assert reports["legacy"].mismatches[a.pk] == (0, 1)
        assert reports["legacy"].mismatches[b.pk] == (1, 0)

    def test_child_relink_and_deferred_parent_delete_order(self):
        a, b = self.model_fixture_factory.create_genre("A"), self.model_fixture_factory.create_genre("B")
        one = self.model_fixture_factory.create_song("One", genre=a)
        two = self.model_fixture_factory.create_song("Two", genre=b)
        two_pk = two.pk
        two.delete(keep_parents=True)

        def encode(pk):
            return pk.hex if connection.vendor == "sqlite" else pk

        with connection.cursor() as cursor:
            cursor.execute("UPDATE grow_song SET track_id = %s WHERE track_id = %s", [encode(two_pk), encode(one.pk)])
        self.assert_projection()
        assert catalogue_bucket_counts() == {b.pk: 1}
        # The first deleted half removes the join; the second must not decrement twice.
        TrackPlaylistRel.objects.filter(track_id=two_pk).delete()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM the_music_tree_genre_kit_track WHERE uuid = %s", [encode(two_pk)])
            cursor.execute("DELETE FROM grow_song WHERE track_id = %s", [encode(two_pk)])
        self.assert_projection()

    def test_read_only_report_and_explicit_verified_repair(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        song = self.model_fixture_factory.create_song("Song", genre=genre)
        song.genre = None
        song.save(update_fields=["genre"])
        report = verify_catalogue_counts()
        assert not report["legacy"].valid
        assert report["shadow"].valid
        GenreCatalogueCount.objects.filter(genre_id=None).update(tracks_count=99)
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("verify_genre_catalogue_counts", stdout=output)
        assert "expected=1, stored=99" in output.getvalue()
        assert stored_catalogue_bucket_counts() == {None: 99}
        output = StringIO()
        call_command("verify_genre_catalogue_counts", repair=True, stdout=output)
        assert "stored=99" in output.getvalue()
        assert "independently verified" in output.getvalue()
        assert all(report.valid for report in verify_catalogue_counts().values())

    def test_missing_configuration_and_unexpected_buckets_fail(self):
        unexpected = uuid4()
        GenreCatalogueCount.objects.create(genre_id=unexpected, tracks_count=0)
        report = verify_catalogue_counts()["shadow"]
        assert report.unexpected == {unexpected}
        reports = verify_catalogue_counts(repair=True)
        assert reports["shadow"].unexpected == {unexpected}
        assert verify_catalogue_counts()["shadow"].valid
        GenrePlaylist.objects.filter(criteria=None).delete()
        assert verify_catalogue_counts()["shadow"].missing_playlists == {None}
        with self.assertRaises(ValueError):
            verify_catalogue_counts(repair=True)
        GenreTreeVersion.objects.all().delete()
        with self.assertRaises(GenreTreeVersion.DoesNotExist):
            verify_catalogue_counts()

    def test_null_uniqueness_nonnegative_and_underflow(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        song = self.model_fixture_factory.create_song("Song", genre=genre)
        GenreCatalogueCount.objects.create(genre_id=None, tracks_count=0)
        for genre_id in (None, genre.pk):
            with self.assertRaises(IntegrityError), transaction.atomic():
                GenreCatalogueCount.objects.create(genre_id=genre_id, tracks_count=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GenreCatalogueCount.objects.filter(genre_id=None).update(tracks_count=-1)
        GenreCatalogueCount.objects.filter(genre_id=genre.pk).delete()
        with self.assertRaises(DatabaseError) as error, transaction.atomic():
            Track.objects.filter(pk=song.pk).update(genre=None)
        assert "underflow" in str(error.exception)
        assert Track.objects.get(pk=song.pk).genre_id == genre.pk
        verify_catalogue_counts(repair=True)
        self.assert_projection()

    def test_failed_post_repair_verification_rolls_back(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        self.model_fixture_factory.create_song("Song", genre=genre)
        GenreCatalogueCount.objects.filter(genre_id=genre.pk).update(tracks_count=99)
        with (
            patch("grow.genre_music.catalogue_verification._compare", return_value=_compare("default")),
            self.assertRaises(RuntimeError),
        ):
            verify_catalogue_counts(repair=True)
        assert stored_catalogue_bucket_counts() == {genre.pk: 99}

    def test_trigger_reversal_and_backfill(self):
        genre = self.model_fixture_factory.create_genre("Genre")
        song = self.model_fixture_factory.create_song("Song", genre=genre)
        migration = import_module("grow.migrations.0113_maintain_genre_catalogue_counts")
        editor = connection.schema_editor()
        migration.drop(apps, editor)
        Track.objects.filter(pk=song.pk).update(genre=None)
        assert stored_catalogue_bucket_counts() != catalogue_bucket_counts()
        GenreCatalogueCount.objects.all().delete()
        migration.create(apps, editor)
        self.assert_projection()

    def test_genre_delete_and_alias_preserve_source_counts(self):
        parent = self.model_fixture_factory.create_genre("Parent", wikidata_id="Q1")
        child = self.model_fixture_factory.create_genre("Child", parent=parent)
        self.model_fixture_factory.create_song("One", genre=child)
        Genre.objects.alias_instance(child, parent, actor=self.admin)
        self.assert_projection()
        assert all(report.valid for report in verify_catalogue_counts().values())
        Genre.objects.delete_instance(parent)
        self.assert_projection()
        assert all(report.valid for report in verify_catalogue_counts().values())

    def test_genre_delete_does_not_transfer_legacy_drift(self):
        parent = self.model_fixture_factory.create_genre("Parent")
        child = self.model_fixture_factory.create_genre("Child", parent=parent)
        self.model_fixture_factory.create_song("Song", genre=child)
        GenrePlaylist.objects.filter(criteria=child).update(direct_songs_count=99)
        assert not verify_catalogue_counts()["legacy"].valid
        Genre.objects.delete_instance(child)
        assert all(report.valid for report in verify_catalogue_counts().values())
