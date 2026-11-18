from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, connections, transaction
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.genre_graph.models import (
    GenreGraphAssignmentState,
    GenreGraphAttribution,
    GenreGraphDataset,
)
from the_music_tree_genre_kit.genre_graph.storage import graph_read_snapshot

from grow.genre_graph.service import write_song_attributions
from grow.genre_music.catalogue_verification import catalogue_bucket_counts
from grow.genre_music.membership import exact_membership_counts, membership_bucket_counts
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song.Song import Song
from tests.utils.ModelFixtureFactory import ModelFixtureFactory
from tests.utils.song_graph import install_song_graph

pytestmark = pytest.mark.django_db


def test_legacy_membership_includes_unassigned_and_unplayable_songs():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Direct")
    song = factory.create_song("Assigned", genre, youtube_video_id=None)
    empty = factory.create_song("Empty", None)
    assert dict(Song.objects.values_list("track_id", "membership_genre_id")) == {
        song.pk: genre.pk,
        empty.pk: None,
    }


def test_semantic_membership_ignores_legacy_genre_and_display_parent():
    factory = ModelFixtureFactory(None)
    display = factory.create_genre("Display")
    semantic = factory.create_genre("Semantic")
    song = factory.create_song("Song", display)
    empty = factory.create_song("Unassigned", display)
    install_song_graph({display: [], semantic: [song]})
    assert dict(Song.objects.values_list("track_id", "membership_genre_id")) == {
        song.pk: semantic.pk,
        empty.pk: None,
    }
    selected = Song.objects.filter(membership_genre=semantic).select_related("membership_genre")
    assert selected.get().membership_genre == semantic
    assert catalogue_bucket_counts() == {semantic.pk: 1, None: 1}
    song.refresh_from_db()
    assert song.genre_id == display.pk


def test_assignment_evidence_does_not_duplicate_membership_and_clear_never_falls_back():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Direct")
    song = factory.create_song("Song", genre)
    dataset = install_song_graph({genre: []})
    dataset = write_song_attributions(
        song_id=song.pk,
        attributions={
            genre.semantic_identity or f"LOCAL:{genre.pk}": [
                {"decisionId": key, "source": "fixture", "rationale": "Independent decision"} for key in ("one", "two")
            ]
        },
        expected_revision=dataset.revision,
        expected_membership_revision=dataset.membership_revision,
        expected_assignment_revision=None,
    )
    assert list(Song.objects.values_list("track_id", "membership_genre_id")) == [(song.pk, genre.pk)]
    write_song_attributions(
        song_id=song.pk,
        attributions={},
        expected_revision=dataset.revision,
        expected_membership_revision=dataset.membership_revision,
        expected_assignment_revision=GenreGraphAssignmentState.objects.get(dataset=dataset, track_id=song.pk).revision,
    )
    assert Song.objects.get(pk=song.pk).membership_genre_id is None


def test_membership_verification_uses_semantic_genre_for_existing_playlist_relations():
    factory = ModelFixtureFactory(None)
    display = factory.create_genre("Display")
    semantic = factory.create_genre("Semantic")
    song = factory.create_song("Song", display)
    install_song_graph({display: [], semantic: [song]})
    display_playlist = GenrePlaylist.objects.get(criteria=display)
    semantic_playlist = GenrePlaylist.objects.get(criteria=semantic)
    TrackPlaylistRel.objects.get_or_create(playlist=semantic_playlist, track=song, defaults={"user": None})

    buckets = membership_bucket_counts()
    assert buckets[(display_playlist.pk, semantic.pk)] == 1
    assert buckets[(semantic_playlist.pk, semantic.pk)] == 1
    exact = exact_membership_counts()
    assert exact.get(display_playlist.pk, 0) == 0
    assert exact[semantic_playlist.pk] == 1


def test_kit_unique_constraint_rejects_a_second_node_for_a_track_in_the_dataset():
    factory = ModelFixtureFactory(None)
    first = factory.create_genre("First")
    second = factory.create_genre("Second")
    song = factory.create_song("Song", None)
    other = factory.create_song("Other", None)
    dataset = install_song_graph({first: [song], second: [other]})
    nodes = list(dataset.nodes.order_by("identity"))
    first_node = dataset.nodes.get(identity=f"LOCAL:{first.pk}")
    second_node = next(node for node in nodes if node.pk != first_node.pk)
    with pytest.raises(IntegrityError), transaction.atomic():
        GenreGraphAttribution.objects.create(track_id=song.pk, node=second_node, dataset_id="grow")
    with pytest.raises(IntegrityError), transaction.atomic():
        GenreGraphAttribution.objects.filter(track_id=other.pk).update(track_id=song.pk)
    assert GenreGraphAttribution.objects.filter(track_id=song.pk).count() == 1


def test_other_datasets_keep_their_own_attribution_for_a_track():
    factory = ModelFixtureFactory(None)
    song = factory.create_song("Song", None)
    for key in ("personal-one", "personal-two"):
        dataset = GenreGraphDataset.objects.create(key=key, payload={})
        node = dataset.nodes.create(identity="one", is_umbrella=False)
        GenreGraphAttribution.objects.create(track_id=song.pk, node=node, dataset=dataset)
    assert GenreGraphAttribution.objects.filter(track_id=song.pk).count() == 2
    assert Song.objects.get(pk=song.pk).membership_genre_id is None


@pytest.mark.parametrize("field", ["dataset_id", "identity"])
def test_assigned_node_identity_cannot_change_across_membership_boundary(field):
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Direct")
    song = factory.create_song("Song", None)
    dataset = install_song_graph({genre: [song]})
    node = dataset.nodes.get(identity=f"LOCAL:{genre.pk}")
    other = GenreGraphDataset.objects.create(key="other", payload={})
    value = other.pk if field == "dataset_id" else "LOCAL:changed"
    with pytest.raises(IntegrityError), transaction.atomic():
        dataset.nodes.filter(pk=node.pk).update(**{field: value})
    assert Song.objects.get(pk=song.pk).membership_genre_id == genre.pk


def test_membership_observes_activation_rollback_without_process_state():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Direct")
    song = factory.create_song("Song", genre)

    def activate_and_abort():
        with transaction.atomic():
            install_song_graph({genre: []})
            assert Song.objects.get(pk=song.pk).membership_genre_id is None
            raise RuntimeError("rollback")

    with pytest.raises(RuntimeError, match="rollback"):
        activate_and_abort()
    assert Song.objects.get(pk=song.pk).membership_genre_id == genre.pk


def test_retired_assignment_never_reuses_legacy_genre():
    factory = ModelFixtureFactory(None)
    legacy = factory.create_genre("Legacy")
    semantic = factory.create_genre("Semantic")
    song = factory.create_song("Song", legacy)
    dataset = install_song_graph({legacy: [], semantic: [song]})
    GenreGraphAttribution.objects.filter(track_id=song.pk).delete()
    dataset.nodes.filter(identity=f"LOCAL:{semantic.pk}").update(is_active=False)
    assert Song.objects.get(pk=song.pk).membership_genre_id is None
    assert Song.objects.get(pk=song.pk).genre_id == legacy.pk


def test_boundary_reversal_and_reinstallation_preserve_sources():
    factory = ModelFixtureFactory(None)
    legacy = factory.create_genre("Legacy")
    semantic = factory.create_genre("Semantic")
    song = factory.create_song("Song", legacy)
    install_song_graph({legacy: [], semantic: [song]})
    migration = import_module("grow.migrations.0140_song_membership_boundary")
    editor = connection.schema_editor()
    before = list(GenreGraphAttribution.objects.values_list("pk", "track_id", "node_id"))
    catalogue = import_module("grow.migrations.0141_semantic_catalogue_projection")
    playlists = import_module("grow.migrations.0142_semantic_playlist_projection")
    playlists.backwards(apps, editor)
    catalogue.backwards(apps, editor)
    migration.drop_boundary(apps, editor)
    assert list(GenreGraphAttribution.objects.values_list("pk", "track_id", "node_id")) == before
    assert Song.objects.get(pk=song.pk).genre_id == legacy.pk
    migration.create_boundary(apps, editor)
    catalogue.forwards(apps, editor)
    playlists.forwards(apps, editor)
    assert Song.objects.get(pk=song.pk).membership_genre_id == semantic.pk


def test_boundary_ddl_and_assignments_roll_back_together():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Direct")
    song = factory.create_song("Song", genre)
    install_song_graph({genre: [song]})
    migration = import_module("grow.migrations.0140_song_membership_boundary")

    def reverse_and_abort():
        with transaction.atomic():
            import_module("grow.migrations.0142_semantic_playlist_projection").backwards(
                apps, connection.schema_editor()
            )
            import_module("grow.migrations.0141_semantic_catalogue_projection").backwards(
                apps, connection.schema_editor()
            )
            migration.drop_boundary(apps, connection.schema_editor())
            GenreGraphAttribution.objects.filter(track_id=song.pk).delete()
            raise RuntimeError("abort migration")

    with pytest.raises(RuntimeError, match="abort migration"):
        reverse_and_abort()
    assert Song.objects.get(pk=song.pk).membership_genre_id == genre.pk


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_concurrent_raw_assignments_serialize_before_single_genre_check():
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    CriteriaPlaylist.objects.get_or_create(user=None, criteria=None, type_id=0)
    factory = ModelFixtureFactory(None)
    song = factory.create_song("Song", None)
    dataset = GenreGraphDataset.objects.create(key="grow", payload={})
    nodes = [dataset.nodes.create(identity=key, is_umbrella=False).pk for key in ("one", "two")]
    barrier = Barrier(2)

    def assign(node_id):
        try:
            barrier.wait(timeout=10)
            with transaction.atomic():
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '10s'")
                GenreGraphAttribution.objects.create(track_id=song.pk, node_id=node_id, dataset_id="grow")
            return True
        except IntegrityError:
            return False
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(assign, nodes))
    assert sorted(results) == [False, True]
    assert GenreGraphAttribution.objects.filter(track_id=song.pk).count() == 1


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_membership_and_graph_revision_share_read_snapshot():
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    CriteriaPlaylist.objects.get_or_create(user=None, criteria=None, type_id=0)
    factory = ModelFixtureFactory(None)
    first = factory.create_genre("First")
    second = factory.create_genre("Second")
    song = factory.create_song("Song", None)
    dataset = install_song_graph({first: [song], second: []})
    dataset.refresh_from_db()
    initial_revision = dataset.membership_revision
    ready, committed = Event(), Event()

    def reassign():
        try:
            if not ready.wait(timeout=10):
                raise RuntimeError("Reader did not establish its snapshot")
            write_song_attributions(
                song_id=song.pk,
                attributions={f"LOCAL:{second.pk}": [{"decisionId": "new", "source": "test", "rationale": "Move"}]},
                expected_revision=dataset.revision,
                expected_membership_revision=initial_revision,
                expected_assignment_revision=GenreGraphAssignmentState.objects.get(
                    dataset=dataset, track_id=song.pk
                ).revision,
            )
            committed.set()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(reassign)
        with graph_read_snapshot():
            assert Song.objects.get(pk=song.pk).membership_genre_id == first.pk
            ready.set()
            if not committed.wait(timeout=10):
                writer.result(timeout=1)
                pytest.fail("Writer did not commit while reader held a snapshot")
            assert GenreGraphDataset.objects.get(pk=dataset.pk).membership_revision == initial_revision
            assert Song.objects.get(pk=song.pk).membership_genre_id == first.pk
        writer.result(timeout=10)
    assert Song.objects.get(pk=song.pk).membership_genre_id == second.pk
    assert GenreGraphDataset.objects.get(pk=dataset.pk).membership_revision != initial_revision
