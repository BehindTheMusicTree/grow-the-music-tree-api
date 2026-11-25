from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.db.models import ProtectedError
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphDataset

from grow.genre_music.catalogue_verification import song_membership_drift
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.song.Song import Song
from tests.utils.ModelFixtureFactory import ModelFixtureFactory
from tests.utils.song_graph import install_song_graph

pytestmark = pytest.mark.django_db


def stored(song):
    return Song.objects.get(pk=song.pk).membership_genre_id


def test_node_deactivation_is_rejected_while_attributed_and_attribution_insert_restores_membership():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Semantic")
    song = factory.create_song("Song", None)
    dataset = install_song_graph({genre: [song]})
    node = dataset.nodes.get(identity=f"LOCAL:{genre.pk}")
    with pytest.raises(IntegrityError), transaction.atomic():
        dataset.nodes.filter(pk=node.pk).update(is_active=False)
    assert stored(song) == genre.pk
    GenreGraphAttribution.objects.filter(track_id=song.pk).delete()
    assert stored(song) is None
    dataset.nodes.filter(pk=node.pk).update(is_active=False)
    dataset.nodes.filter(pk=node.pk).update(is_active=True)
    GenreGraphAttribution.objects.create(track_id=song.pk, node_id=node.pk, dataset_id="grow")
    assert stored(song) == genre.pk
    assert song_membership_drift() == {}


def test_permanent_graph_binding_cannot_be_rebound_so_membership_cannot_follow_a_rebind():
    factory = ModelFixtureFactory(None)
    first = factory.create_genre("First")
    second = factory.create_genre("Second")
    song = factory.create_song("Song", None)
    install_song_graph({first: [song], second: []})
    with pytest.raises(IntegrityError), transaction.atomic():
        Genre.objects.filter(pk=first.pk).update(graph_node=second.graph_node_id)
    assert stored(song) == first.pk


def test_dataset_creation_switches_to_semantic_genre_and_deletion_is_protected():
    factory = ModelFixtureFactory(None)
    legacy = factory.create_genre("Legacy")
    semantic = factory.create_genre("Semantic")
    song = factory.create_song("Song", legacy)
    assert stored(song) == legacy.pk
    dataset = install_song_graph({legacy: [], semantic: [song]})
    assert stored(song) == semantic.pk
    with pytest.raises(ProtectedError):
        dataset.delete()
    assert stored(song) == semantic.pk
    assert song_membership_drift() == {}


def test_drift_check_ignores_genres_outside_the_graph_for_unattributed_songs():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Semantic")
    factory.create_genre("Outside the graph")
    song = factory.create_song("Song", None)
    unattributed = factory.create_song("Unattributed", None)
    install_song_graph({genre: [song]})
    assert stored(unattributed) is None
    assert song_membership_drift() == {}


@pytest.mark.postgres
def test_drift_check_reports_a_stale_stored_genre():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Semantic")
    song = factory.create_song("Song", None)
    install_song_graph({genre: [song]})
    assert song_membership_drift() == {}
    if connection.vendor != "postgresql":
        pytest.skip("Bypassing the guard trigger is PostgreSQL-only")
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
    Song.objects.filter(pk=song.pk).update(membership_genre=None)
    assert song_membership_drift() == {song.pk: (genre.pk, None)}


@pytest.mark.postgres
def test_direct_write_of_a_derived_genre_is_rejected_once_a_dataset_exists():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Semantic")
    other = factory.create_genre("Other")
    song = factory.create_song("Song", None)
    install_song_graph({genre: [song], other: []})
    with pytest.raises(DatabaseError, match="cannot be written directly"), transaction.atomic():
        Song.objects.filter(pk=song.pk).update(membership_genre=other)
    assert stored(song) == genre.pk
    Song.objects.filter(pk=song.pk).update(membership_genre=genre)
    assert stored(song) == genre.pk


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_attribution_insert_and_node_deactivation_leave_no_stale_membership():
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    CriteriaPlaylist.objects.get_or_create(user=None, criteria=None, type_id=0)
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Semantic")
    song = factory.create_song("Song", None)
    dataset = install_song_graph({genre: []})
    node = dataset.nodes.get(identity=f"LOCAL:{genre.pk}")
    barrier = Barrier(2)

    def attribute():
        try:
            barrier.wait(timeout=10)
            GenreGraphAttribution.objects.create(track_id=song.pk, node_id=node.pk, dataset_id="grow")
        except IntegrityError:
            pass  # the node was retired first
        finally:
            connections.close_all()

    def deactivate():
        try:
            barrier.wait(timeout=10)
            GenreGraphDataset.objects.get(pk=dataset.pk).nodes.filter(pk=node.pk).update(is_active=False)
        except IntegrityError:
            pass  # the attribution committed first
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attribute), pool.submit(deactivate)]
        for future in futures:
            future.result(timeout=30)
    assert song_membership_drift() == {}
    assert stored(song) == (genre.pk if GenreGraphAttribution.objects.filter(track_id=song.pk).exists() else None)
