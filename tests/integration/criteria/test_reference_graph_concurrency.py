import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import connections, transaction
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.genre_graph.storage import GraphRevisionConflict

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportReceipt
from grow.genre_graph.models import GenreGraphImport
from grow.genre_graph.service import import_reference_graph, reference_dataset
from grow.genre_music.source_gate import lock_catalogue_sources
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.import_run.ImportRun import ImportRun
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song.Song import Song
from grow.track.bulk_import.merge import _merge
from tests.integration.criteria.test_reference_graph import _retirement, _without_identity, graph_client, import_graph
from tests.utils.ModelFixtureFactory import ModelFixtureFactory


@pytest.fixture(autouse=True)
def reference_configuration(db):
    # Transaction tests flush migration seeds between cases.
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    if not GenrePlaylist.objects.filter(user=None, criteria=None).exists():
        GenrePlaylist.objects.create(user=None, criteria=None, type_id=0)


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_concurrent_retirements_cannot_overwrite_reviewed_graph():
    payload = json.loads((Path(__file__).parents[2] / "fixtures/genre_graph/regional-v2.json").read_text())
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    original = import_graph(payload)
    mapping = deepcopy(GenreGraphImport.objects.get(pk=original.revision).mapping)
    del mapping["LOCAL:french-dub"]
    changed = _without_identity(payload, "LOCAL:french-dub")
    barrier = Barrier(2)

    def retire(target):
        try:
            barrier.wait(timeout=10)
            with transaction.atomic():
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '10s'")
                result = import_reference_graph(
                    payload=changed,
                    mapping=mapping,
                    expected_revision=original.revision,
                    curation_exported_on=changed["curationExportedOn"],
                    retirements={"LOCAL:french-dub": _retirement(target)},
                )
            return result.revision
        except GraphRevisionConflict:
            return None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(retire, [None, "LOCAL:reggae"]))
    successes = [revision for revision in results if revision is not None]
    assert successes == [reference_dataset().revision]
    assert GenreGraphImport.objects.count() == 2


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_song_import_waits_for_graph_activation_then_rejects_unreviewed_publication():
    payload = json.loads((Path(__file__).parents[2] / "fixtures/genre_graph/regional-v2.json").read_text())
    run = BulkImportRun.objects.create(kind=ImportRun.Kind.SONGS)
    backend = Queue()

    def publish():
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend.put(cursor.fetchone()[0])
            with pytest.raises(ValidationError, match="Song imports require"):
                _merge(run.pk, {}, False)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            lock_catalogue_sources()
            import_graph(payload)
            songs = list(Song.objects.values_list("pk", flat=True))
            future = pool.submit(publish)
            pid = backend.get(timeout=10)
            deadline = monotonic() + 10
            with connections["default"].cursor() as cursor:
                while True:
                    cursor.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = %s "
                        "AND locktype = 'advisory' AND NOT granted)",
                        [pid],
                    )
                    if cursor.fetchone()[0]:
                        break
                    if future.done() or monotonic() >= deadline:
                        pytest.fail("Song publication did not wait for graph activation")
                    sleep(0.01)
        future.result(timeout=10)
    assert list(Song.objects.values_list("pk", flat=True)) == songs
    assert not ImportReceipt.objects.filter(pk=run.pk).exists()


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_playlist_tree_response_and_etag_share_one_snapshot(monkeypatch):
    payload = json.loads((Path(__file__).parents[2] / "fixtures/genre_graph/regional-v2.json").read_text())
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    dataset = import_graph(payload)
    genre = Genre.objects.get(graph_node__dataset=dataset, graph_node__identity="LOCAL:dub")
    original_name = genre.name
    changed_name = "Concurrent snapshot name"
    module = import_module("grow.view.viewset.model.playlist.children.criteria.genre.GenrePlaylistViewSet")
    original_rows = module._tree_rows
    cache.clear()

    def update():
        try:
            Genre.objects.filter(pk=genre.pk).update(_name=changed_name)
        finally:
            connections.close_all()

    def rows_after_update(*args, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(update).result(timeout=15)
        return original_rows(*args, **kwargs)

    monkeypatch.setattr(module, "_tree_rows", rows_after_update)
    client = APIClient()
    path = reverse("genre-playlist-list") + "tree/"
    response = client.get(path, {"tree_name": "canonical"})
    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert original_name in names
    assert changed_name not in names
    old_etag = response["ETag"]
    monkeypatch.setattr(module, "_tree_rows", original_rows)
    response = client.get(path, {"tree_name": "canonical"}, HTTP_IF_NONE_MATCH=old_etag)
    assert response.status_code == 200
    assert response["ETag"] != old_etag
    assert changed_name in {row["name"] for row in response.json()}


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_concurrent_assignment_api_edits_preserve_the_winners_complete_evidence():
    payload = json.loads((Path(__file__).parents[2] / "fixtures/genre_graph/regional-v2.json").read_text())
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    song = ModelFixtureFactory(None).create_song("Concurrent assignment", None)
    import_graph(payload)
    path = reverse("song-attributions", kwargs={"song_id": song.pk})
    reviewed = APIClient().get(path).json()
    barrier = Barrier(2)

    def edit(identity):
        evidence = [
            {"decisionId": f"{identity}:{index}", "source": "fixture", "rationale": "Concurrent explicit evidence"}
            for index in range(2)
        ]
        try:
            barrier.wait(timeout=10)
            response = graph_client("curator").put(
                path,
                {
                    "expectedRevision": reviewed["revision"],
                    "expectedMembershipRevision": reviewed["membershipRevision"],
                    "expectedAssignmentRevision": reviewed["assignmentRevision"],
                    "attributions": {identity: evidence},
                },
                format="json",
            )
            return response.status_code, identity, evidence, response.json()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["LOCAL:french-dub", "LOCAL:jamaican-dub"]))
    assert sorted(result[0] for result in results) == [200, 409]
    _, identity, evidence, tokens = next(result for result in results if result[0] == 200)
    final = APIClient().get(path).json()
    assert final["attributions"] == {identity: evidence}
    assert {key: final[key] for key in tokens} == tokens
