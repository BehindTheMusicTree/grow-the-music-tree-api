from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import connection, transaction
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphDataset

from grow.genre_music.catalogue_verification import catalogue_bucket_counts, stored_catalogue_bucket_counts
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from tests.utils.ModelFixtureFactory import ModelFixtureFactory
from tests.utils.song_graph import install_song_graph

pytestmark = pytest.mark.django_db


def assert_counts(expected):
    assert catalogue_bucket_counts() == expected
    assert stored_catalogue_bucket_counts() == expected


def test_catalogue_follows_raw_assignment_and_clear_without_legacy_fallback():
    factory = ModelFixtureFactory(None)
    legacy = factory.create_genre("Legacy")
    first = factory.create_genre("First")
    second = factory.create_genre("Second")
    song = factory.create_song("Song", legacy, youtube_video_id=None)
    empty = factory.create_song("Empty", legacy)
    assert_counts({legacy.pk: 2})
    dataset = install_song_graph({legacy: [], first: [song], second: []})
    assert_counts({first.pk: 1, None: 1})
    assignment = GenreGraphAttribution.objects.get(track_id=song.pk)
    assignment.node = dataset.nodes.get(identity=f"LOCAL:{second.pk}")
    assignment.save(update_fields=["node"])
    assert_counts({second.pk: 1, None: 1})
    # An obsolete legacy write cannot change effective membership.
    type(song).objects.filter(pk=song.pk).update(genre=first)
    assert_counts({second.pk: 1, None: 1})
    assignment.delete()
    assert_counts({None: 2})
    empty.delete()
    assert_counts({None: 1})


def test_catalogue_assignment_rollback_restores_counts():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre(f"Genre {uuid4()}")
    song = factory.create_song("Song", genre)
    install_song_graph({genre: [song]})

    def abort_assignment_change():
        with transaction.atomic():
            GenreGraphAttribution.objects.filter(track_id=song.pk).delete()
            assert_counts({None: 1})
            raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        abort_assignment_change()
    assert_counts({genre.pk: 1})


def test_batched_assignment_changes_conserve_null_and_assigned_buckets():
    factory = ModelFixtureFactory(None)
    first = factory.create_genre("First")
    second = factory.create_genre("Second")
    songs = [factory.create_song(f"Song {index}", None) for index in range(4)]
    dataset = install_song_graph({first: [], second: []})
    first_node = dataset.nodes.get(identity=f"LOCAL:{first.pk}")
    second_node = dataset.nodes.get(identity=f"LOCAL:{second.pk}")
    GenreGraphAttribution.objects.bulk_create(
        [GenreGraphAttribution(track_id=song.pk, node=first_node) for song in songs[:3]]
    )
    assert_counts({first.pk: 3, None: 1})
    GenreGraphAttribution.objects.filter(track_id__in=[song.pk for song in songs[:2]]).update(node=second_node)
    assert_counts({first.pk: 1, second.pk: 2, None: 1})
    GenreGraphAttribution.objects.filter(track_id__in=[song.pk for song in songs[:3]]).delete()
    assert_counts({None: 4})


def test_unrelated_dataset_and_empty_transitions_preserve_counts_and_version():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Genre")
    factory.create_song("Song", genre)
    token = GenreTreeVersion.current_token()
    unrelated = GenreGraphDataset.objects.create(key="other", payload={})
    unrelated.delete()
    GenreGraphDataset.objects.filter(pk="missing").update(payload={})
    GenreGraphDataset.objects.filter(pk="missing").delete()
    GenreGraphAttribution.objects.filter(pk=-1).update(track_id=uuid4())
    assert_counts({genre.pk: 1})
    assert GenreTreeVersion.current_token() == token


def test_catalogue_projection_reversal_and_reinstallation_recount_each_authority():
    factory = ModelFixtureFactory(None)
    legacy = factory.create_genre("Legacy")
    semantic = factory.create_genre("Semantic")
    song = factory.create_song("Song", legacy)
    install_song_graph({legacy: [], semantic: [song]})
    migration = import_module("grow.migrations.0141_semantic_catalogue_projection")
    editor = connection.schema_editor()
    assert_counts({semantic.pk: 1})
    migration.backwards(apps, editor)
    assert stored_catalogue_bucket_counts() == {legacy.pk: 1}
    migration.forwards(apps, editor)
    assert_counts({semantic.pk: 1})


@pytest.mark.postgres
@pytest.mark.parametrize(
    "table",
    [
        "the_music_tree_genre_kit_genregraphattribution",
        "the_music_tree_genre_kit_genregraphnode",
        "the_music_tree_genre_kit_genregraphdataset",
    ],
)
def test_semantic_source_truncate_and_rollback(table):
    factory = ModelFixtureFactory(None)
    legacy = factory.create_genre("Legacy")
    semantic = factory.create_genre("Semantic")
    song = factory.create_song("Song", legacy)
    install_song_graph({legacy: [], semantic: [song]})
    with transaction.atomic():
        with connection.cursor() as cursor:
            # Fire the deferred FK checks queued by the fixtures; TRUNCATE refuses a table with pending trigger events.
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(f"TRUNCATE {connection.ops.quote_name(table)} CASCADE")
        assert catalogue_bucket_counts() == stored_catalogue_bucket_counts()
        transaction.set_rollback(True)
    assert_counts({semantic.pk: 1})
