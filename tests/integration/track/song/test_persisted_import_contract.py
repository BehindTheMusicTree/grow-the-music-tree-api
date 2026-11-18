from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.bulk_import.lifecycle import queue_attempt
from grow.model.import_run.ImportRun import ImportRun
from grow.track.bulk_import.contract import require_complete_run, require_declared_part
from grow.track.bulk_import.merge import merge_song_import_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def run():
    return BulkImportRun.objects.create(
        kind=ImportRun.Kind.SONGS,
        mode=BulkImportRun.Mode.DELTA,
        committed_on=timezone.now(),
        graph_revision=uuid4(),
        membership_revision=uuid4(),
        expected_parts={"songs": 0, "assignments": 0, "deletions": 0},
    )


@pytest.mark.parametrize(
    "parts",
    [
        [],
        0,
        {},
        {"songs": 0},
        {"songs": True, "assignments": 0, "deletions": 0},
        {"songs": 0, "assignments": -1, "deletions": 0},
        {"songs": 0, "assignments": 0, "deletions": 0, "unknown": 0},
    ],
)
def test_stored_manifest_is_revalidated_on_upload_and_completion(run, parts):
    BulkImportRun.objects.filter(pk=run.pk).update(expected_parts=parts)
    run.refresh_from_db()
    with pytest.raises(ValidationError, match="expected_parts"):
        require_complete_run(run)
    with pytest.raises(ValidationError, match="expected_parts"):
        require_declared_part(run, "assignments", 0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "invalid"),
        ("graph_revision", None),
        ("membership_revision", "invalid"),
    ],
)
def test_in_memory_partial_review_and_invalid_tokens_are_rejected(run, field, value):
    setattr(run, field, value)
    with pytest.raises(ValidationError):
        require_complete_run(run)


def test_worker_rechecks_persisted_manifest_before_song_writes(run):
    BulkImportRun.objects.filter(pk=run.pk).update(expected_parts={"songs": 0})
    attempt = queue_attempt(run)
    with (
        patch("grow.track.bulk_import.merge.projection.lock_if_live") as projection,
        pytest.raises(ValidationError, match="expected_parts"),
    ):
        merge_song_import_run(run.pk, None, False, attempt.pk)
    projection.assert_not_called()
    attempt.refresh_from_db()
    assert attempt.state == ImportAttempt.State.FAILED
    assert not attempt.data_applied
    assert not ImportReceipt.objects.filter(pk=run.pk).exists()


def test_completed_receipt_retry_only_cleans_up_even_if_manifest_changed(run):
    BulkImportRun.objects.filter(pk=run.pk).update(expected_parts={"songs": 0})
    receipt = {"imported": 4, "skipped": 0, "stepTimings": []}
    ImportReceipt.objects.create(run_id=run.pk, result=receipt)
    attempt = queue_attempt(run)
    merge = Mock(side_effect=AssertionError("A committed import must never merge again"))
    with (
        patch("grow.track.bulk_import.merge._merge", merge),
        patch("grow.track.bulk_import.merge.invalidate_search_cache"),
        patch("grow.track.bulk_import.merge.queue_song_search_build"),
    ):
        assert merge_song_import_run(run.pk, None, False, attempt.pk) == receipt
    merge.assert_not_called()
    assert not BulkImportRun.objects.filter(pk=run.pk).exists()
    attempt.refresh_from_db()
    assert attempt.state == ImportAttempt.State.SUCCEEDED
    assert attempt.data_applied


def test_stored_delta_manifest_rejects_multiple_deletion_parts(run):
    BulkImportRun.objects.filter(pk=run.pk).update(expected_parts={"songs": 0, "assignments": 0, "deletions": 2})
    run.refresh_from_db()
    for validate in (lambda: require_complete_run(run), lambda: require_declared_part(run, "assignments", 0)):
        with pytest.raises(ValidationError, match="at most one deletions part"):
            validate()
