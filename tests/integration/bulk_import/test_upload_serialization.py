import gzip
import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from django.http import Http404
from rest_framework.exceptions import ValidationError

from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportPart import ImportPart
from grow.model.import_run.ImportRun import ImportRun
from grow.track.bulk_import.SongAssignmentStaging import SongAssignmentStaging
from grow.track.bulk_import.SongImportStaging import SongImportStaging
from grow.view.viewset.mixin.BulkImportRunMixin import assignment_part_upload_action, bulk_import_run_actions

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
MODULE = "grow.view.viewset.mixin.BulkImportRunMixin"


def reviewed_data(**parts):
    return {
        "graph_revision": str(uuid4()),
        "membership_revision": str(uuid4()),
        "expected_parts": {"songs": 1, "assignments": 1, **parts},
    }


def request(body=b"", data=None):
    return SimpleNamespace(data=data or {}, body=body, user=None, owner=None, auth=SimpleNamespace(role="pipeline"), headers={})


def actions(loader):
    return bulk_import_run_actions(
        "songs/",
        ImportRun.Kind.SONGS,
        SongImportStaging,
        loader,
        lambda *args: {},
        "musicbrainz_recording_id",
        extra_staging_models=(SongAssignmentStaging,),
    )[:4]


def in_connection(operation):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '10s'")
            cursor.execute("SET statement_timeout = '15s'")
        return operation()
    finally:
        close_old_connections()


@pytest.mark.parametrize("operation", ["commit", "abandon", "replace"])
def test_inflight_part_is_serialized_with_commit_abandonment_and_replacement(operation):
    run = BulkImportRun.objects.create(
        kind=ImportRun.Kind.SONGS,
        graph_revision=uuid4(),
        membership_revision=uuid4(),
        expected_parts={"songs": 1, "assignments": 1},
    )
    held, release, started, finished = Event(), Event(), Event(), Event()
    mbid = uuid4()

    def loader(run_id, part, body):
        if body.read() == b"first":
            held.set()
            if not release.wait(10):
                raise TimeoutError("Upload test did not release loader")
        SongImportStaging.objects.filter(run_id=run_id, part=part).delete()
        SongImportStaging.objects.create(
            run_id=run_id, part=part, musicbrainz_recording_id=mbid, title="Song", artist="Artist"
        )
        SongAssignmentStaging.objects.filter(run_id=run_id, part=part).delete()
        SongAssignmentStaging.objects.create(run_id=run_id, part=part, musicbrainz_recording_id=mbid, assignments={})
        return 1

    create, upload, _, commit = actions(loader)

    def second():
        started.set()
        if operation == "commit":
            response = commit(None, request(), str(run.pk))
        elif operation == "abandon":
            response = create(None, request(data=reviewed_data()))
        else:
            response = upload(None, request(b"second"), str(run.pk), "0")
        finished.set()
        return response

    with (
        patch(f"{MODULE}.spooled_body", side_effect=lambda req: io.BytesIO(req.body)),
        patch(f"{MODULE}.require_reviewed_contract"),
        patch(f"{MODULE}.require_complete_run"),
        patch(f"{MODULE}.enqueue_merge"),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        first = pool.submit(in_connection, lambda: upload(None, request(b"first"), str(run.pk), "0"))
        try:
            assert held.wait(10)
            other = pool.submit(in_connection, second)
            assert started.wait(10)
            assert not finished.wait(0.2)
        finally:
            release.set()
        assert first.result(timeout=15).status_code == 200
        assert other.result(timeout=15).status_code in {200, 201, 202}

    expected = 0 if operation == "abandon" else 1
    assert SongImportStaging.objects.filter(run_id=run.pk).count() == expected
    assert SongAssignmentStaging.objects.filter(run_id=run.pk).count() == expected
    if operation == "commit":
        run.refresh_from_db()
        assert run.committed_on is not None
    elif operation == "abandon":
        assert not BulkImportRun.objects.filter(pk=run.pk).exists()


@pytest.mark.parametrize("upload_kind", ["songs", "deletions"])
@pytest.mark.parametrize("operation", ["commit", "abandon"])
def test_upload_rechecks_run_after_spooling(upload_kind, operation):
    run = BulkImportRun.objects.create(
        kind=ImportRun.Kind.SONGS,
        mode=BulkImportRun.Mode.DELTA,
        graph_revision=uuid4(),
        membership_revision=uuid4(),
        expected_parts={"songs": 1, "assignments": 1, "deletions": 1},
    )
    create, upload, deletions, commit = actions(lambda *args: pytest.fail("Late song part was loaded"))

    def spool(req):
        if operation == "commit":
            commit(None, request(), str(run.pk))
        else:
            create(None, request(data=reviewed_data()))
        return io.BytesIO(gzip.compress(json.dumps({"musicbrainz_recording_id": str(uuid4())}).encode()))

    invoke = (
        (lambda: upload(None, request(), str(run.pk), "0"))
        if upload_kind == "songs"
        else (lambda: deletions(None, request(), str(run.pk)))
    )
    with (
        patch(f"{MODULE}.spooled_body", side_effect=spool),
        patch(f"{MODULE}.require_reviewed_contract"),
        patch(f"{MODULE}.enqueue_merge"),
        pytest.raises(ValidationError if operation == "commit" else Http404),
    ):
        invoke()
    assert not SongImportStaging.objects.exists()
    assert not BulkImportDeletion.objects.exists()


@pytest.mark.parametrize("operation", ["commit", "abandon", "replace"])
def test_assignment_upload_serializes_with_publication_and_abandonment(operation):

    run = BulkImportRun.objects.create(
        kind=ImportRun.Kind.SONGS,
        mode=BulkImportRun.Mode.DELTA,
        graph_revision=uuid4(),
        membership_revision=uuid4(),
        expected_parts={"songs": 0, "assignments": 1, "deletions": 0},
    )
    held, release, started, finished = Event(), Event(), Event(), Event()
    mbid = uuid4()

    def loader(run_id, part, body):
        if body.read() == b"first":
            held.set()
            if not release.wait(10):
                raise TimeoutError("Assignment upload test did not release loader")
        SongAssignmentStaging.objects.filter(run_id=run_id, part=part).delete()
        SongAssignmentStaging.objects.create(run_id=run_id, part=part, musicbrainz_recording_id=mbid, assignments={})
        return 1

    create, _, _, commit = actions(lambda *args: pytest.fail("Song loader called for assignments"))
    upload = assignment_part_upload_action("songs/")

    def second():
        started.set()
        if operation == "commit":
            response = commit(None, request(), str(run.pk))
        elif operation == "abandon":
            response = create(None, request(data=reviewed_data()))
        else:
            response = upload(None, request(b"second"), str(run.pk), "0")
        finished.set()
        return response

    with (
        patch(f"{MODULE}.spooled_body", side_effect=lambda req: io.BytesIO(req.body)),
        patch(f"{MODULE}.load_assignment_part", side_effect=loader),
        patch(f"{MODULE}.require_reviewed_contract"),
        patch(f"{MODULE}.enqueue_merge"),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        first = pool.submit(in_connection, lambda: upload(None, request(b"first"), str(run.pk), "0"))
        try:
            assert held.wait(10)
            other = pool.submit(in_connection, second)
            assert started.wait(10)
            assert not finished.wait(0.2)
        finally:
            release.set()
        assert first.result(timeout=15).status_code == 200
        assert other.result(timeout=15).status_code in {200, 201, 202}

    expected = 0 if operation == "abandon" else 1
    assert SongAssignmentStaging.objects.filter(run_id=run.pk).count() == expected
    assert ImportPart.objects.filter(run_id=run.pk).count() == expected
    if operation == "commit":
        run.refresh_from_db()
        assert run.committed_on is not None


@pytest.mark.parametrize("operation", ["commit", "abandon"])
def test_assignment_upload_rechecks_run_after_spooling(operation):

    run = BulkImportRun.objects.create(
        kind=ImportRun.Kind.SONGS,
        mode=BulkImportRun.Mode.DELTA,
        graph_revision=uuid4(),
        membership_revision=uuid4(),
        expected_parts={"songs": 0, "assignments": 0, "deletions": 0},
    )
    # Declare one part for upload validation; the mocked commit only tests the run's locked state transition.
    BulkImportRun.objects.filter(pk=run.pk).update(expected_parts={"songs": 0, "assignments": 1, "deletions": 0})
    create, _, _, commit = actions(lambda *args: pytest.fail("Unexpected song loader"))
    upload = assignment_part_upload_action("songs/")

    def spool(req):
        if operation == "commit":
            commit(None, request(), str(run.pk))
        else:
            create(None, request(data=reviewed_data()))
        return io.BytesIO(b"body")

    with (
        patch(f"{MODULE}.spooled_body", side_effect=spool),
        patch(f"{MODULE}.require_complete_run"),
        patch(f"{MODULE}.require_reviewed_contract"),
        patch(f"{MODULE}.enqueue_merge"),
        patch(f"{MODULE}.load_assignment_part", side_effect=lambda *args: pytest.fail("Late assignments loaded")),
        pytest.raises(ValidationError if operation == "commit" else Http404),
    ):
        upload(None, request(), str(run.pk), "0")
    assert not SongAssignmentStaging.objects.exists()
    assert not ImportPart.objects.exists()
