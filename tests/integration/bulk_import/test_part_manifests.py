import io

import pytest
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportPart import ImportPart
from grow.bulk_import.manifests import record_part, require_complete_parts
from grow.model.import_run.ImportRun import ImportRun
from grow.track.bulk_import.SongAssignmentStaging import SongAssignmentStaging

pytestmark = pytest.mark.django_db


@pytest.fixture
def run():
    return BulkImportRun.objects.create(kind=ImportRun.Kind.SONGS)


def receipt(run, part, count):
    record_part(run=run, stream="assignments", part=part, count=count, body=io.BytesIO(b"payload"))


def test_missing_parts_and_unlogged_reset_require_reupload(run):
    streams = {"assignments": (SongAssignmentStaging, 2)}
    receipt(run, 0, 1)
    with pytest.raises(ValidationError, match="incomplete"):
        require_complete_parts(run, streams)
    receipt(run, 1, 0)
    with pytest.raises(ValidationError, match="lost or changed"):
        require_complete_parts(run, streams)
    SongAssignmentStaging.objects.create(
        run_id=run.pk, part=0, musicbrainz_recording_id="b1a9c0e9-d987-4042-ae91-78d6a3267d69", assignments={}
    )
    require_complete_parts(run, streams)


def test_empty_parts_and_empty_delta_are_explicit(run):
    require_complete_parts(run, {"assignments": (SongAssignmentStaging, 0)})
    receipt(run, 0, 0)
    require_complete_parts(run, {"assignments": (SongAssignmentStaging, 1)})
    with pytest.raises(ValidationError, match="incomplete"):
        require_complete_parts(run, {"assignments": (SongAssignmentStaging, 0)})


def test_reupload_replaces_receipt_atomically_and_run_cleanup_cascades(run):
    receipt(run, 0, 1)
    first = ImportPart.objects.get(run=run)

    def fail_after_receipt():
        with transaction.atomic():
            record_part(run=run, stream="assignments", part=0, count=2, body=io.BytesIO(b"replacement"))
            raise RuntimeError("COPY failed")

    with pytest.raises(RuntimeError):
        fail_after_receipt()
    first.refresh_from_db()
    assert first.row_count == 1
    receipt(run, 0, 3)
    assert ImportPart.objects.get(run=run).row_count == 3
    assert ImportPart.objects.count() == 1
    run.delete()
    assert not ImportPart.objects.exists()


def test_undeclared_staging_parts_are_rejected(run):
    SongAssignmentStaging.objects.create(
        run_id=run.pk, part=1, musicbrainz_recording_id="b1a9c0e9-d987-4042-ae91-78d6a3267d69", assignments={}
    )
    with pytest.raises(ValidationError, match="lost or changed"):
        require_complete_parts(run, {"assignments": (SongAssignmentStaging, 0)})


@pytest.mark.parametrize(
    "metadata",
    [
        {"graph_revision": "b1a9c0e9-d987-4042-ae91-78d6a3267d69"},
        {"membership_revision": "b1a9c0e9-d987-4042-ae91-78d6a3267d69"},
        {"expected_parts": {}},
        {
            "kind": ImportRun.Kind.ARTISTS,
            "graph_revision": "b1a9c0e9-d987-4042-ae91-78d6a3267d69",
            "membership_revision": "b1a9c0e9-d987-4042-ae91-78d6a3267d69",
            "expected_parts": {},
        },
    ],
)
def test_database_rejects_partial_or_non_song_review_metadata(metadata):
    with pytest.raises(IntegrityError), transaction.atomic():
        BulkImportRun.objects.create(**{"kind": ImportRun.Kind.SONGS, **metadata})


def test_large_missing_manifest_is_rejected_without_enumerating_declared_parts(run):
    receipt(run, 0, 0)
    with pytest.raises(ValidationError, match="incomplete"):
        require_complete_parts(run, {"assignments": (SongAssignmentStaging, 10**30)})
