from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Event
from time import monotonic
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import OperationalError, ProgrammingError, close_old_connections, connection, transaction
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks
from the_music_tree_genre_kit.track.Track import Track

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.genre_music.catalogue_verification import (
    catalogue_bucket_counts,
    stored_catalogue_bucket_counts,
    verify_catalogue_counts,
)
from grow.genre_music.membership import membership_bucket_counts, stored_membership_bucket_counts
from grow.genre_music.summary import genre_playlist_summaries
from grow.genre_music.summary_inputs import clear_summary_inputs_cache
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.history.HistoryAction import HistoryAction
from grow.model.import_run.ImportRun import ImportRun
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.playlist.GenreCatalogueCount import GenreCatalogueCount
from grow.model.song.Song import Song
from grow.track.bulk_import import merge as song_merge
from grow.track.bulk_import.SongImportStaging import SongImportStaging
from tests.utils.ModelFixtureFactory import ModelFixtureFactory

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def in_connection(operation):
    close_old_connections()
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '10s'")
            return operation()
    finally:
        close_old_connections()


@pytest.fixture
def catalogue():
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    # Transaction tests flush the migration seeds. Establish their configuration explicitly.
    if not GenrePlaylist.objects.filter(user=None, criteria=None).exists():
        GenrePlaylist.objects.create(user=None, criteria=None, type_id=0)
    factory = ModelFixtureFactory(default_user=None)
    a, b, c = [factory.create_genre(name) for name in ("A", "B", "C")]
    song = factory.create_song("Song", genre=a)
    return factory, a, b, c, song


def race(first, second):
    held, release, started, finished = Event(), Event(), Event(), Event()

    def hold():
        first()
        held.set()
        if not release.wait(5):
            raise TimeoutError("Test did not release source writer")

    def wait():
        started.set()
        second()
        finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(in_connection, hold)
        try:
            assert held.wait(5)
            contender = pool.submit(in_connection, wait)
            assert started.wait(5)
            assert not finished.wait(0.1), "Source exclusion was bypassed"
        finally:
            release.set()
        writer.result(timeout=10)
        contender.result(timeout=10)
    assert stored_catalogue_bucket_counts() == catalogue_bucket_counts()
    assert stored_membership_bucket_counts() == membership_bucket_counts()


@pytest.mark.parametrize("action", ["move", "delete"])
@pytest.mark.parametrize("rollback_first", [False, True])
@pytest.mark.parametrize("rollback_second", [False, True])
def test_managed_stale_move_move_and_move_delete(catalogue, action, rollback_first, rollback_second):
    _, _, b, c, song = catalogue
    stale = Song.objects.get(pk=song.pk)

    def first():
        Song.objects.update_instance(song, genre=b)
        transaction.set_rollback(rollback_first)

    def second():
        if action == "move":
            Song.objects.update_instance(stale, genre=c)
        else:
            Song.objects.delete_instance(stale)
        transaction.set_rollback(rollback_second)

    race(first, second)
    assert all(report.valid for report in verify_catalogue_counts().values())


@pytest.mark.parametrize("source", ["child_insert", "child_delete", "move", "delete", "create"])
@pytest.mark.parametrize("repair", [False, True])
def test_verification_waits_for_every_source_write(catalogue, source, repair):
    factory, a, b, _, song = catalogue
    pk = song.pk
    if source == "child_insert":
        song.delete(keep_parents=True)
        verify_catalogue_counts(repair=True)

    def first():
        if source == "child_insert":
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO grow_song (track_id, is_manually_edited) VALUES (%s, false)", [pk])
        elif source == "child_delete":
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM grow_song WHERE track_id = %s", [pk])
        elif source == "move":
            Track.objects.filter(pk=pk).update(genre=b)
        elif source == "delete":
            Song.objects.get(pk=pk).delete()
        else:
            factory.create_song("New", genre=a)

    def second():
        reports = verify_catalogue_counts(repair=repair)
        assert reports["shadow"].valid

    race(first, second)
    assert verify_catalogue_counts()["shadow"].valid


def test_verification_rejects_repeatable_read(catalogue):
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(ValueError, match="READ COMMITTED"):
            verify_catalogue_counts()


@pytest.mark.parametrize("rollback_move", [False, True])
def test_genre_delete_waits_for_song_assignment(catalogue, rollback_move):
    _, a, b, _, song = catalogue

    def move():
        Song.objects.update_instance(song, genre=b)
        transaction.set_rollback(rollback_move)

    def delete_genre():
        Genre.objects.delete_instance(a)

    race(move, delete_genre)
    assert all(report.valid for report in verify_catalogue_counts().values())
    song.refresh_from_db()
    assert song.genre_id == (None if rollback_move else b.pk)


def test_import_snapshot_excludes_concurrent_admin_edit(catalogue):
    _, _, b, c, song = catalogue
    mbid = uuid4()
    Song.objects.filter(pk=song.pk).update(musicbrainz_recording_id=mbid)
    run = BulkImportRun.objects.create(kind=ImportRun.Kind.SONGS, mode=BulkImportRun.Mode.DELTA)
    SongImportStaging.objects.create(
        run_id=run.pk, part=0, musicbrainz_recording_id=mbid, title="Imported", artist="Artist", genre_name=b.name
    )
    params = {
        "run": run.pk,
        "user": None,
        "genre_changed": HistoryAction.GENRE_CHANGED.value,
        "genre_type": CriteriaTypePks.GENRE.value,
        "content_type": ContentType.objects.get_for_model(Song).pk,
    }
    snapshot, release, started, finished = Event(), Event(), Event(), Event()
    original = song_merge.run_steps

    def pause_after_snapshot(cursor, steps, *args, **kwargs):
        result = original(cursor, steps, *args, **kwargs)
        if steps[0][0] == "song_import":
            snapshot.set()
            if not release.wait(5):
                raise TimeoutError("Import test did not release snapshot")
        return result

    def edit():
        started.set()
        Song.objects.update_instance(song, genre=c)
        finished.set()

    with (
        patch.object(song_merge, "run_steps", side_effect=pause_after_snapshot),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        importer = pool.submit(in_connection, lambda: song_merge._merge(run.pk, params, False))
        try:
            assert snapshot.wait(5)
            editor = pool.submit(in_connection, edit)
            assert started.wait(5)
            assert not finished.wait(0.1), "Admin edit bypassed the import source gate"
        finally:
            release.set()
        importer.result(timeout=10)
        editor.result(timeout=10)
    assert all(report.valid for report in verify_catalogue_counts().values())
    assert stored_membership_bucket_counts() == membership_bucket_counts()
    song.refresh_from_db()
    assert song.genre_id == c.pk


def test_savepoint_failure_preserves_outer_projection(catalogue):
    _, a, b, c, song = catalogue

    def failed_mutation():
        with transaction.atomic():
            Song.objects.update_instance(song, genre=c)
            raise ValueError("abort inner mutation")

    with transaction.atomic():
        Song.objects.update_instance(song, genre=b)
        with pytest.raises(ValueError, match="abort inner mutation"):
            failed_mutation()
        assert catalogue_bucket_counts() == {b.pk: 1}
        assert all(report.valid for report in verify_catalogue_counts().values())
        # The instance still holds the rolled-back genre; manager refresh must handle it.
        Song.objects.update_instance(song, genre=a)
    assert all(report.valid for report in verify_catalogue_counts().values())


@pytest.mark.parametrize("table", ["grow_song", "the_music_tree_genre_kit_track"])
def test_truncate_rebuilds_shadow_and_rollback_restores_it(catalogue, table):
    before = catalogue_bucket_counts()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE {connection.ops.quote_name(table)} CASCADE")
        assert catalogue_bucket_counts() == {}
        assert stored_catalogue_bucket_counts() == {}
        transaction.set_rollback(True)
    assert catalogue_bucket_counts() == before
    assert stored_catalogue_bucket_counts() == before


def test_unrelated_updates_do_not_rewrite_catalogue(catalogue):
    _, _, _, _, song = catalogue

    def stored_versions():
        with connection.cursor() as cursor:
            cursor.execute("SELECT genre_id, tracks_count, xmin::text FROM grow_genre_catalogue_count ORDER BY id")
            return cursor.fetchall()

    versions = stored_versions()
    Track.objects.filter(pk=song.pk).update(title="Renamed")
    Song.objects.filter(pk=song.pk).update(is_manually_edited=True)
    assert stored_versions() == versions
    assert all(report.valid for report in verify_catalogue_counts().values())


@pytest.mark.parametrize("warm", [False, True])
def test_summary_is_coherent_when_writer_commits_before_materialization(catalogue, warm):
    _, a, b, _, song = catalogue
    playlist = GenrePlaylist.objects.get(criteria=a)
    clear_summary_inputs_cache()
    if warm:
        genre_playlist_summaries([playlist.pk])
    committed = []

    def commit_after_statement(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if "UNION ALL" in sql and not committed:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(in_connection, lambda: Song.objects.update_instance(song, genre=b)).result(timeout=10)
            committed.append(True)
        return result

    with connection.execute_wrapper(commit_after_statement):
        summary = genre_playlist_summaries([playlist.pk])[playlist.pk]
    assert committed == [True]
    assert summary["catalogue"]["genre_only_tracks_count"] == 1
    assert summary["tracks_count"] == 1
    current = genre_playlist_summaries([playlist.pk])[playlist.pk]
    assert current["catalogue"]["genre_only_tracks_count"] == 0
    assert current["tracks_count"] == 0


@pytest.mark.parametrize("warm", [False, True])
def test_summary_cache_discards_rolled_back_inputs(catalogue, warm):
    _, a, b, _, song = catalogue
    playlist = GenrePlaylist.objects.get(criteria=a)
    clear_summary_inputs_cache()
    if warm:
        genre_playlist_summaries([playlist.pk])
    with transaction.atomic():
        Song.objects.update_instance(song, genre=b)
        changed = genre_playlist_summaries([playlist.pk])[playlist.pk]
        assert changed["catalogue"]["genre_only_tracks_count"] == 0
        assert changed["tracks_count"] == 0
        transaction.set_rollback(True)
    restored = genre_playlist_summaries([playlist.pk])[playlist.pk]
    assert restored["catalogue"]["genre_only_tracks_count"] == 1
    assert restored["tracks_count"] == 1


@pytest.mark.parametrize("warm", [False, True])
def test_summary_inputs_use_one_query(catalogue, warm, django_assert_num_queries):
    _, a, _, _, _ = catalogue
    playlist = GenrePlaylist.objects.get(criteria=a)
    clear_summary_inputs_cache()
    if warm:
        genre_playlist_summaries([playlist.pk])
    with django_assert_num_queries(1):
        genre_playlist_summaries([playlist.pk])


@pytest.fixture
def uninstalled_catalogue_projection(catalogue):
    migration = import_module("grow.migrations.0113_maintain_genre_catalogue_counts")
    migration.drop(apps, connection.schema_editor())
    GenreCatalogueCount.objects.all().delete()
    try:
        yield migration
    finally:
        # Failed migration transactions must leave no partial functions or triggers.
        # Reinstalling also restores the schema for the next transaction test.
        migration.drop(apps, connection.schema_editor())
        GenreCatalogueCount.objects.all().delete()
        with transaction.atomic():
            migration.create(apps, connection.schema_editor())


def test_migration_busy_old_writer_fails_cleanly(catalogue, uninstalled_catalogue_projection):
    _, _, b, _, song = catalogue
    held, release = Event(), Event()

    def old_writer():
        Song.objects.update_instance(song, genre=b)
        held.set()
        if not release.wait(5):
            raise TimeoutError("Migration test did not release old writer")

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(in_connection, old_writer)
        try:
            assert held.wait(5)
            with pytest.raises(OperationalError, match="could not obtain lock"), transaction.atomic():
                uninstalled_catalogue_projection.create(apps, connection.schema_editor())
        finally:
            release.set()
        writer.result(timeout=10)
    assert not GenreCatalogueCount.objects.exists()
    with transaction.atomic():
        uninstalled_catalogue_projection.create(apps, connection.schema_editor())
    assert all(report.valid for report in verify_catalogue_counts().values())


def test_migration_excludes_new_writer_until_backfill_commits(catalogue, uninstalled_catalogue_projection):
    _, _, b, _, song = catalogue

    def migrate():
        uninstalled_catalogue_projection.create(apps, connection.schema_editor())

    def new_writer():
        Song.objects.update_instance(song, genre=b)

    race(migrate, new_writer)
    assert all(report.valid for report in verify_catalogue_counts().values())


def test_migration_busy_gate_fails_without_holding_relation_locks(catalogue, uninstalled_catalogue_projection):
    held, release = Event(), Event()

    def gate_holder():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(716731928417)")
        held.set()
        if not release.wait(5):
            raise TimeoutError("Migration test did not release gate")

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(in_connection, gate_holder)
        try:
            assert held.wait(5)
            with pytest.raises(ProgrammingError, match="source gate is busy"), transaction.atomic():
                uninstalled_catalogue_projection.create(apps, connection.schema_editor())
        finally:
            release.set()
        writer.result(timeout=10)
    assert not GenreCatalogueCount.objects.exists()


def test_migration_rejects_writer_queued_at_old_source_gate(catalogue, uninstalled_catalogue_projection):
    _, _, b, _, song = catalogue
    held, release, started = Event(), Event(), Event()
    writer_pid = []

    def gate_holder():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(716731928417)")
        held.set()
        if not release.wait(5):
            raise TimeoutError("Migration test did not release gate")

    def queued_writer():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            writer_pid.append(cursor.fetchone()[0])
        started.set()
        # Old writers reach the gate through the database's BEFORE trigger,
        # after PostgreSQL has already acquired a relation lock for UPDATE.
        Track.objects.filter(pk=song.pk).update(genre=b)

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(in_connection, gate_holder)
        try:
            assert held.wait(5)
            writer = pool.submit(in_connection, queued_writer)
            assert started.wait(5)
            deadline = monotonic() + 3
            while True:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT wait_event FROM pg_stat_activity WHERE pid = %s", writer_pid)
                    if cursor.fetchone()[0] == "advisory":
                        break
                if monotonic() >= deadline:
                    raise TimeoutError("Old writer did not queue at source gate")
                release.wait(0.01)
            with pytest.raises(OperationalError, match="could not obtain lock"), transaction.atomic():
                uninstalled_catalogue_projection.create(apps, connection.schema_editor())
        finally:
            release.set()
        holder.result(timeout=10)
        writer.result(timeout=10)
    assert not GenreCatalogueCount.objects.exists()
