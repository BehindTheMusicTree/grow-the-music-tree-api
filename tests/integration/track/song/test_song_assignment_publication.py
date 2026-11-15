import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection, transaction
from rest_framework.exceptions import ValidationError
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.genre_graph.assignments import assignment_snapshot
from the_music_tree_genre_kit.genre_graph.models import (
    GenreGraphAssignmentState,
    GenreGraphAttributionRevision,
    GenreGraphEvidence,
    GenreGraphNode,
)
from the_music_tree_genre_kit.genre_graph.storage import GraphRevisionConflict

from grow.genre_music.source_gate import lock_catalogue_sources
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.track.bulk_import.assignment_publication import assignment_write_transaction, publish_assignments
from grow.track.bulk_import.SongAssignmentStaging import SongAssignmentStaging
from tests.integration.criteria.test_reference_graph import import_graph
from tests.utils.ModelFixtureFactory import ModelFixtureFactory

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
EVIDENCE = {"decisionId": "import-test", "source": "fixture", "rationale": "Reviewed complete set"}


@pytest.fixture
def population():
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    GenrePlaylist.objects.get_or_create(user=None, criteria=None, type_id=0)
    payload = json.loads((Path(__file__).parents[3] / "fixtures/genre_graph/regional-v2.json").read_text())
    dataset = import_graph(payload)
    factory = ModelFixtureFactory(None)
    songs = [factory.create_song(f"Song {i}", None, musicbrainz_recording_id=uuid4()) for i in range(3)]
    return dataset, songs


def stage(songs, assignments):
    SongAssignmentStaging.objects.bulk_create(
        [
            SongAssignmentStaging(run_id=1, part=i, musicbrainz_recording_id=s.musicbrainz_recording_id, assignments=a)
            for i, (s, a) in enumerate(zip(songs, assignments, strict=True))
        ]
    )


def publish(dataset, songs, *, locked=(), graph=None, membership=None):
    with (
        assignment_write_transaction(
            expected_graph=graph or dataset.revision,
            expected_membership=membership or dataset.membership_revision,
        ) as locked_dataset,
        connection.cursor() as cursor,
    ):
        cursor.execute("CREATE TEMP TABLE song_import (mbid uuid, track_id uuid, is_locked boolean) ON COMMIT DROP")
        cursor.executemany(
            "INSERT INTO song_import VALUES (%s, %s, %s)",
            [(s.musicbrainz_recording_id, s.pk, s.pk in locked) for s in songs],
        )
        publish_assignments(run_id=1, dataset=locked_dataset)


def test_multiple_evidence_empty_sets_locked_songs_and_idempotent_retry(population):
    dataset, songs = population
    assignments = {"LOCAL:french-dub": [EVIDENCE, {**EVIDENCE, "decisionId": "second"}]}
    stage(songs, [assignments, {}, {"LOCAL:roots": [EVIDENCE]}])
    publish(dataset, songs, locked=[songs[2].pk])
    assert assignment_snapshot(dataset=dataset, track_id=songs[0].pk) == assignments
    assert assignment_snapshot(dataset=dataset, track_id=songs[1].pk) == {}
    assert not GenreGraphAssignmentState.objects.filter(track_id=songs[2].pk).exists()
    assert GenreGraphEvidence.objects.filter(decision_id__in=[EVIDENCE["decisionId"], "second"]).count() == 2
    dataset.refresh_from_db()
    assert GenreGraphAssignmentState.objects.count() == 2
    states = list(GenreGraphAssignmentState.objects.order_by("track_id").values_list("revision", flat=True))
    history = list(GenreGraphAttributionRevision.objects.order_by("revision").values_list("revision", flat=True))
    membership = dataset.membership_revision
    publish(dataset, songs, locked=[songs[2].pk])
    dataset.refresh_from_db()
    assert dataset.membership_revision == membership
    assert list(GenreGraphAssignmentState.objects.order_by("track_id").values_list("revision", flat=True)) == states
    assert (
        list(GenreGraphAttributionRevision.objects.order_by("revision").values_list("revision", flat=True)) == history
    )


def test_replacement_archives_old_and_empty_new_complete_sets(population):
    dataset, songs = population
    stage(songs, [{"LOCAL:dub": [EVIDENCE]}, {}, {}])
    publish(dataset, songs)
    dataset.refresh_from_db()
    previous = GenreGraphAssignmentState.objects.get(track_id=songs[0].pk).revision
    SongAssignmentStaging.objects.filter(run_id=1).update(assignments={})
    publish(dataset, songs)
    assert assignment_snapshot(dataset=dataset, track_id=songs[0].pk) == {}
    assert GenreGraphAttributionRevision.objects.get(pk=previous).attributions == {"LOCAL:dub": [EVIDENCE]}
    current = GenreGraphAssignmentState.objects.get(track_id=songs[0].pk).revision
    assert current != previous
    assert GenreGraphAttributionRevision.objects.get(pk=current).attributions == {}


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "extra",
        "duplicate",
        "unknown",
        "conflicting",
        "existing-evidence",
        "multiple-genres",
        "locked-multiple-genres",
    ],
)
def test_invalid_population_or_evidence_rolls_back_everything(population, failure):
    dataset, songs = population
    stage(songs, [{"LOCAL:dub": [EVIDENCE]}, {}, {}])
    row = SongAssignmentStaging.objects.first()
    if failure == "missing":
        row.delete()
    elif failure == "extra":
        SongAssignmentStaging.objects.create(run_id=1, part=4, musicbrainz_recording_id=uuid4(), assignments={})
    elif failure == "duplicate":
        row.pk = None
        row.part = 4
        row.save()
    elif failure in {"multiple-genres", "locked-multiple-genres"}:
        row.assignments = {"LOCAL:dub": [EVIDENCE], "LOCAL:french-dub": [EVIDENCE]}
        row.save()
    elif failure == "unknown":
        row.assignments = {"LOCAL:absent": [EVIDENCE]}
        row.save()
    elif failure == "conflicting":
        SongAssignmentStaging.objects.filter(part=1).update(
            assignments={"LOCAL:roots": [{**EVIDENCE, "source": "different"}]}
        )
    else:
        GenreGraphEvidence.objects.create(
            dataset=dataset, decision_id=EVIDENCE["decisionId"], source="different", rationale=EVIDENCE["rationale"]
        )
    evidence_count = GenreGraphEvidence.objects.count()
    with pytest.raises(ValidationError):
        publish(dataset, songs, locked=[songs[0].pk] if failure == "locked-multiple-genres" else [])
    assert GenreGraphEvidence.objects.count() == evidence_count
    assert not GenreGraphAssignmentState.objects.exists()
    assert not GenreGraphAttributionRevision.objects.exists()


@pytest.mark.parametrize("token", ["graph", "membership"])
def test_reviewed_tokens_rechecked_before_any_publication(population, token):
    dataset, songs = population
    stage(songs, [{}, {}, {}])
    with pytest.raises(GraphRevisionConflict):
        publish(dataset, songs, **{token: uuid4()})
    assert not GenreGraphAssignmentState.objects.exists()


def test_outer_failure_rolls_back_assignments_evidence_history_and_membership(population):
    dataset, songs = population
    stage(songs, [{"LOCAL:dub": [EVIDENCE]}, {}, {}])
    evidence_count = GenreGraphEvidence.objects.count()

    def fail_after_publication():
        with transaction.atomic():
            publish(dataset, songs)
            raise RuntimeError("projection failed")

    with pytest.raises(RuntimeError, match="projection failed"):
        fail_after_publication()
    old_membership = dataset.membership_revision
    dataset.refresh_from_db()
    assert dataset.membership_revision == old_membership
    assert GenreGraphEvidence.objects.count() == evidence_count
    assert not GenreGraphAssignmentState.objects.exists()
    assert not GenreGraphAttributionRevision.objects.exists()


def test_existing_locked_complete_set_and_history_survive_new_import(population):
    dataset, songs = population
    original = {"LOCAL:french-dub": [EVIDENCE, {**EVIDENCE, "decisionId": "second"}]}
    stage(songs, [original, {}, {}])
    publish(dataset, songs)
    dataset.refresh_from_db()
    state = GenreGraphAssignmentState.objects.get(track_id=songs[0].pk).revision
    history = list(GenreGraphAttributionRevision.objects.values_list("revision", flat=True))
    token = dataset.membership_revision
    ignored = {**EVIDENCE, "decisionId": "ignored-locked", "source": "new import"}
    SongAssignmentStaging.objects.filter(part=0).update(assignments={"LOCAL:roots": [ignored]})

    publish(dataset, songs, locked=[songs[0].pk])

    dataset.refresh_from_db()
    assert assignment_snapshot(dataset=dataset, track_id=songs[0].pk) == original
    assert GenreGraphAssignmentState.objects.get(track_id=songs[0].pk).revision == state
    assert list(GenreGraphAttributionRevision.objects.values_list("revision", flat=True)) == history
    assert dataset.membership_revision == token
    assert not GenreGraphEvidence.objects.filter(decision_id="ignored-locked").exists()


@pytest.mark.parametrize("invalid", ["unknown", "retired", "conflicting-evidence"])
def test_locked_input_still_requires_valid_reviewed_identities_and_evidence(population, invalid):
    dataset, songs = population
    identity = "LOCAL:dub"
    if invalid == "unknown":
        identity = "LOCAL:unknown"
    elif invalid == "retired":
        GenreGraphNode.objects.filter(dataset=dataset, identity=identity).update(is_active=False)
    else:
        GenreGraphEvidence.objects.create(
            dataset=dataset,
            decision_id=EVIDENCE["decisionId"],
            source="immutable original",
            rationale=EVIDENCE["rationale"],
        )
    stage(songs, [{identity: [EVIDENCE]}, {}, {}])
    with pytest.raises(ValidationError):
        publish(dataset, songs, locked=[songs[0].pk])
    assert not GenreGraphAssignmentState.objects.exists()


def test_empty_delta_population_preserves_all_existing_assignments(population):
    dataset, songs = population
    stage(songs, [{"LOCAL:dub": [EVIDENCE]}, {}, {}])
    publish(dataset, songs)
    dataset.refresh_from_db()
    token = dataset.membership_revision
    history = GenreGraphAttributionRevision.objects.count()
    SongAssignmentStaging.objects.all().delete()

    publish(dataset, [])

    dataset.refresh_from_db()
    assert dataset.membership_revision == token
    assert GenreGraphAttributionRevision.objects.count() == history
    assert assignment_snapshot(dataset=dataset, track_id=songs[0].pk) == {"LOCAL:dub": [EVIDENCE]}


@pytest.mark.parametrize("token", ["revision", "membership_revision"])
def test_cas_is_rechecked_after_waiting_for_another_publication(population, token):
    dataset, songs = population
    stage(songs, [{"LOCAL:dub": [EVIDENCE]}, {}, {}])
    held, release, started, finished = Event(), Event(), Event(), Event()

    def writer():
        close_old_connections()
        try:
            with transaction.atomic():
                lock_catalogue_sources()
                locked = type(dataset).objects.select_for_update().get(pk=dataset.pk)
                setattr(locked, token, uuid4())
                locked.save(update_fields=[token])
                held.set()
                if not release.wait(10):
                    raise TimeoutError("Publication test did not release writer")
        finally:
            close_old_connections()

    def contender():
        close_old_connections()
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '10s'")
                started.set()
                with pytest.raises(GraphRevisionConflict):
                    publish(dataset, songs)
                finished.set()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(writer)
        try:
            assert held.wait(10)
            second = pool.submit(contender)
            assert started.wait(10)
            assert not finished.wait(0.2)
        finally:
            release.set()
        first.result(timeout=15)
        second.result(timeout=15)
    assert not GenreGraphAssignmentState.objects.exists()
    assert not GenreGraphEvidence.objects.filter(decision_id=EVIDENCE["decisionId"]).exists()
