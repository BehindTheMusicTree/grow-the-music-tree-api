import json
import re
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection, connections
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_graph import GraphValidationError
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphDataset

from grow.authentication.ApiKeyAuthentication import PipelineUser
from grow.authentication.Principal import Principal
from grow.bulk_import.analyze import tables
from grow.bulk_import.BulkImportRun import GENRE_GRAPH_KIND, BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.bulk_import.lifecycle import queue_attempt
from grow.genre_graph.bulk_import.GenreGraphImportPayload import GenreGraphImportPayload
from grow.genre_graph.bulk_import.merge import (
    GRAPH_REVISION_MODELS,
    SONG_PROJECTION_MODELS,
    merge_reference_graph_import_run,
)
from grow.genre_graph.models import GenreGraphAssignmentBackup, GenreGraphImport
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song.Song import Song
from tests.integration.criteria.test_reference_graph import _retirement, _without_identity
from tests.utils.curation_export import record_graph_export
from tests.utils.ModelFixtureFactory import ModelFixtureFactory

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def reference_configuration(db):
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    if not GenrePlaylist.objects.filter(user=None, criteria=None).exists():
        GenrePlaylist.objects.create(user=None, criteria=None, type_id=0)


@pytest.fixture
def payload():
    path = Path(__file__).parents[2] / "fixtures/genre_graph/regional-v5.json"
    payload = json.loads(path.read_text())
    record_graph_export(payload)
    return payload


def client(role):
    api = APIClient()
    api.force_authenticate(user=PipelineUser(), token=Principal(role=role, email=None, sub=None))
    return api


def body(payload, revision=None, mapping=None):
    return {
        "graph": payload,
        "mapping": mapping if mapping is not None else {node["id"]: None for node in payload["nodes"]},
        "expectedRevision": revision,
    }


def runs_url():
    return reverse("reference-graph-import-runs")


def status_of(api, task_id):
    return api.get(reverse("genre-list") + f"graph/import/{task_id}/status/").json()


def test_graph_import_rejects_an_artists_recovery_request(payload):
    source = PipelineRunRequest.objects.create(kind="sync", status="failed")
    recovery = PipelineRunRequest.objects.create(kind="sync_artists", status="running", source_run=source)
    response = client("pipeline").post(
        runs_url(), body(payload), format="json", HTTP_X_PIPELINE_RUN_REQUEST=str(recovery.uuid)
    )
    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    assert not BulkImportRun.objects.filter(kind=GENRE_GRAPH_KIND).exists()


@pytest.mark.parametrize("published", [False, True])
def test_public_revision_reads_only_the_graph_token(payload, published):
    revision = None
    if published:
        response = client("pipeline").post(runs_url(), body(payload), format="json")
        assert response.status_code == status.HTTP_202_ACCEPTED
        polled = status_of(client("pipeline"), response.json()["taskId"])
        assert polled["status"] == "success"
        revision = polled["result"]["revision"]

    with CaptureQueriesContext(connection) as queries:
        response = APIClient().get(reverse("reference-graph-revision"))

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"revision": revision}
    assert response["Cache-Control"] == "no-store"
    assert len(queries) == 1
    columns, source = queries[0]["sql"].split(" FROM ", 1)
    assert source.startswith(f'"{GenreGraphDataset._meta.db_table}"')
    assert columns.removesuffix(' AS "revision"') == f'SELECT "{GenreGraphDataset._meta.db_table}"."revision"'


def test_bootstrap_import_then_success_with_both_revisions_and_initial_backup(payload):
    song = ModelFixtureFactory(None).create_song("Unassigned", None)

    response = client("pipeline").post(runs_url(), body(payload), format="json")

    assert response.status_code == status.HTTP_202_ACCEPTED, response.content
    polled = status_of(client("pipeline"), response.json()["taskId"])
    assert polled["status"] == "success", polled
    dataset = GenreGraphDataset.objects.get(pk="grow")
    assert polled["result"] == {
        "revision": str(dataset.revision),
        "membershipRevision": str(dataset.membership_revision),
    }
    assert GenreGraphImport.objects.get().has_initial_assignment_backup
    assert GenreGraphAssignmentBackup.objects.filter(song_uuid=song.pk).exists()
    assert not GenreGraphAttribution.objects.filter(track_id=song.pk).exists()
    assert not BulkImportRun.objects.exists()
    assert not GenreGraphImportPayload.objects.exists()
    attempt = ImportAttempt.objects.get(kind=GENRE_GRAPH_KIND)
    assert {step["label"] for step in attempt.completed_steps} >= {"backup_assignments", "migrate_assignments"}


def test_two_lineage_parents_then_import_succeeds_with_cardinality_alerts(payload):
    payload["relations"].append(
        {
            "childId": "LOCAL:roots",
            "parentId": "LOCAL:dub",
            "type": "classification",
            "provenance": {"decisionId": "extra-parent", "source": "test", "rationale": "second parent"},
        }
    )

    response = client("pipeline").post(runs_url(), body(payload), format="json")

    polled = status_of(client("pipeline"), response.json()["taskId"])
    assert polled["status"] == "success", polled
    alerts = CurationReviewItem.objects.filter(reason=CurationReviewItem.Reason.CLASSIFICATION_CARDINALITY)
    assert list(alerts.values_list("item_id", flat=True)) == ["LOCAL:roots"]


def test_permissions(payload):
    assert APIClient().post(runs_url(), body(payload), format="json").status_code == 401
    assert client("viewer").post(runs_url(), body(payload), format="json").status_code == 403
    assert client("curator").post(runs_url(), body(payload), format="json").status_code == 403


def test_stale_expected_revision_then_409_and_nothing_queued(payload):
    response = client("pipeline").post(runs_url(), body(payload, str(uuid4())), format="json")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert not BulkImportRun.objects.exists()


def test_invalid_graph_then_400(payload):
    payload = {**payload, "nodes": "nope"}

    response = client("pipeline").post(runs_url(), body(payload, mapping={}), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not BulkImportRun.objects.exists()


def test_second_post_while_one_is_queued_then_409(payload):
    with patch("grow.view.genre_graph.enqueue_merge"):
        first = client("pipeline").post(runs_url(), body(payload), format="json")
    assert first.status_code == status.HTTP_202_ACCEPTED

    second = client("pipeline").post(runs_url(), body(payload), format="json")

    assert second.status_code == status.HTTP_409_CONFLICT
    assert BulkImportRun.objects.filter(kind=GENRE_GRAPH_KIND).count() == 1


@pytest.mark.postgres
def test_concurrent_posts_queue_only_one_attempt(payload):
    barrier = Barrier(2)

    def submit():
        try:
            api = client("pipeline")
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '10s'")
            barrier.wait(timeout=10)
            return api.post(runs_url(), body(payload), format="json")
        finally:
            connections.close_all()

    with patch("grow.view.genre_graph.enqueue_merge") as enqueue, ThreadPoolExecutor(max_workers=2) as pool:
        responses = [pool.submit(submit) for _ in range(2)]
        results = [pending.result(timeout=20) for pending in responses]

    assert sorted(response.status_code for response in results) == [202, 409]
    assert BulkImportRun.objects.filter(kind=GENRE_GRAPH_KIND).count() == 1
    assert GenreGraphImportPayload.objects.count() == 1
    assert ImportAttempt.objects.filter(kind=GENRE_GRAPH_KIND).count() == 1
    enqueue.assert_called_once()


def test_revision_changed_between_post_and_merge_then_failed_with_conflict_and_cleaned_up(payload):
    api = client("pipeline")
    first = api.post(runs_url(), body(payload), format="json")
    assert status_of(api, first.json()["taskId"])["status"] == "success"
    revision = str(GenreGraphDataset.objects.get(pk="grow").revision)
    with patch("grow.view.genre_graph.enqueue_merge") as enqueue:
        queued = api.post(runs_url(), body(payload, revision), format="json")
    assert queued.status_code == status.HTTP_202_ACCEPTED
    GenreGraphDataset.objects.filter(pk="grow").update(revision=uuid4())
    run, attempt = enqueue.call_args.args[1:]

    with pytest.raises(Exception, match="revision changed"):
        enqueue.call_args.args[0](run.pk, run.user_id, run.record, attempt_id=attempt.pk)

    failed = status_of(api, queued.json()["taskId"])
    assert failed["status"] == "failed"
    assert failed["error"].startswith("GraphRevisionConflict: Reference graph revision changed")
    assert not BulkImportRun.objects.exists()
    assert not GenreGraphImportPayload.objects.exists()


def test_unmapped_existing_genre_then_kept_with_alert(payload):
    orphan = ModelFixtureFactory(None).create_genre("Orphan")
    api = client("pipeline")

    with patch("grow.view.genre_graph.enqueue_merge"):
        response = api.post(runs_url(), body(payload), format="json")
    run = BulkImportRun.objects.get()
    attempt = ImportAttempt.objects.get()

    merge_reference_graph_import_run(run.pk, run.user_id, run.record, attempt_id=attempt.pk)

    assert status_of(api, response.json()["taskId"])["status"] != "failed"
    orphan.refresh_from_db()
    assert orphan.graph_node_id is None
    item = CurationReviewItem.objects.get(reason="genre_not_in_graph")
    assert item.evidence["genreUuid"] == str(orphan.pk)


def test_unlisted_merge_error_then_failed_with_the_generic_message(payload):
    api = client("pipeline")
    with patch("grow.view.genre_graph.enqueue_merge"):
        response = api.post(runs_url(), body(payload), format="json")
    run = BulkImportRun.objects.get()
    attempt = ImportAttempt.objects.get()

    with (
        patch("grow.genre_graph.bulk_import.merge._merge", side_effect=RuntimeError("SELECT secret")),
        pytest.raises(RuntimeError),
    ):
        merge_reference_graph_import_run(run.pk, run.user_id, run.record, attempt_id=attempt.pk)

    failed = status_of(api, response.json()["taskId"])
    assert failed["status"] == "failed"
    assert "secret" not in failed["error"]
    assert failed["error"].startswith("RuntimeError: import merge failed")


@pytest.mark.postgres
def test_tables_written_by_the_import_are_all_analyzed(payload):
    factory = ModelFixtureFactory(None)
    source = factory.create_genre("Existing genre")
    song = factory.create_song("Assigned", source)
    api = client("pipeline")
    mapping = {node["id"]: None for node in payload["nodes"]}
    mapping["LOCAL:french-dub"] = str(source.pk)

    def publish(request):
        with patch("grow.view.genre_graph.enqueue_merge"):
            response = api.post(runs_url(), request, format="json")
        assert response.status_code == 202, response.content
        run = BulkImportRun.objects.get()
        assert GenreGraphImportPayload.objects.get(run_id=run.pk).payload == {
            "graph": request["graph"],
            "mapping": request["mapping"],
            "expected_revision": request["expectedRevision"],
            "retirements": request.get("retirements"),
        }
        attempt = ImportAttempt.objects.get(run_id=run.pk)
        with CaptureQueriesContext(connection) as queries:
            result = merge_reference_graph_import_run(run.pk, run.user_id, run.record, attempt_id=attempt.pk)
        attempt.refresh_from_db()
        assert ImportReceipt.objects.get(pk=run.pk).result == result
        return result, {step["label"]: step for step in attempt.completed_steps}, [q["sql"] for q in queries]

    original, steps, sql = publish(body(payload, mapping=mapping))
    assert steps.keys() >= {"lock_graph_sources", "replace_graph", "publish_graph_revision", "analyze", "commit"}
    assert steps["materialize_song_genres"]["rowcount"] == 0

    pattern = re.compile(r'^\s*(?:INSERT INTO|UPDATE|DELETE FROM|TRUNCATE(?: TABLE)?)\s+(?:ONLY\s+)?"?(\w+)"?', re.I)
    written = {m.group(1) for query in sql if (m := pattern.match(query))}
    written = {t for t in written if not t.startswith(("grow_assignment_", "graph_assignment_changes_"))}
    # Telemetry and the merge's own bookkeeping are not catalogue data.
    written -= {
        "grow_import_attempt",
        "grow_import_receipt",
        "grow_import_part",
        "grow_bulk_import_run",
        "grow_bulk_import_deletion",
    }
    written -= {"grow_genre_graph_import_payload", "django_q_ormq", "django_q_task"}
    written.discard("grow_song")  # The bootstrap UPDATE changed zero rows.
    assert written <= {query.removeprefix("ANALYZE ").strip('"') for query in sql if query.startswith("ANALYZE ")}

    mapping = GenreGraphImport.objects.get(pk=original["revision"]).mapping
    replay, steps, sql = publish(body(payload, original["revision"], mapping))
    assert replay == original
    assert "materialize_song_genres" not in steps
    assert not any(query.startswith("ANALYZE ") or "grow_song" in query for query in sql)
    assert GenreGraphImport.objects.count() == GenreGraphAssignmentBackup.objects.count() == 1

    edited = deepcopy(payload)
    edited["nodes"][0]["name"] += " (updated)"
    updated, steps, sql = publish(body(edited, original["revision"], mapping))
    assert updated["revision"] != original["revision"]
    assert steps["materialize_song_genres"]["rowcount"] == 0
    assert not any("grow_song" in query or "grow_affected_song_" in query for query in sql)
    analyzed = {q.removeprefix("ANALYZE ").strip('"') for q in sql if q.startswith("ANALYZE ")}
    assert {table for table in analyzed if not table.startswith("graph_access_stage_")} == set(
        tables(GRAPH_REVISION_MODELS)
    )

    retired = body(_without_identity(edited, "LOCAL:french-dub"), updated["revision"], mapping)
    del retired["mapping"]["LOCAL:french-dub"]
    retired["retirements"] = {"LOCAL:french-dub": _retirement(None)}
    _, steps, sql = publish(retired)
    assert steps["capture_retired_song_candidates"]["rowcount"] == 1
    assert steps["materialize_song_genres"]["rowcount"] == 1
    assert set(tables(SONG_PROJECTION_MODELS)) <= {
        q.removeprefix("ANALYZE ").strip('"') for q in sql if q.startswith("ANALYZE ")
    }
    assert Song.objects.get(pk=song.pk).membership_genre_id is None


def test_committed_graph_run_retries_cleanup_without_republication(payload):
    api = client("pipeline")
    with patch("grow.view.genre_graph.enqueue_merge"):
        response = api.post(runs_url(), body(payload), format="json")
    assert response.status_code == 202, response.content
    run = BulkImportRun.objects.get()
    attempt = ImportAttempt.objects.get()

    with (
        patch("grow.bulk_import.lifecycle._finalize", side_effect=RuntimeError("cleanup interrupted")),
        pytest.raises(RuntimeError, match="cleanup interrupted"),
    ):
        merge_reference_graph_import_run(run.pk, run.user_id, run.record, attempt_id=attempt.pk)

    receipt = ImportReceipt.objects.get(pk=run.pk)
    assert receipt.result["revision"] == str(GenreGraphDataset.objects.get().revision)
    attempt.refresh_from_db()
    assert attempt.state == ImportAttempt.State.FAILED
    assert attempt.data_applied
    retry = queue_attempt(run)
    with patch("grow.genre_graph.bulk_import.merge._merge") as merge:
        result = merge_reference_graph_import_run(run.pk, run.user_id, run.record, attempt_id=retry.pk)
    merge.assert_not_called()
    assert result == receipt.result
    assert GenreGraphImport.objects.count() == 1
    assert not BulkImportRun.objects.exists()
    assert not GenreGraphImportPayload.objects.exists()
