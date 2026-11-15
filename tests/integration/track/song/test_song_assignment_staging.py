import gzip
import io
import json

import pytest
from django.db import connection
from rest_framework.exceptions import ValidationError

from grow.track.bulk_import.assignment_part_loader import load_part
from grow.track.bulk_import.SongAssignmentStaging import SongAssignmentStaging

MBID = "b1a9c0e9-d987-4042-ae91-78d6a3267d69"
OTHER = "0c4b2a83-6a5c-4c1d-9f43-3b9d8f0b2e11"
EVIDENCE = {"decisionId": "d1", "source": "curation", "rationale": "Reviewed"}


def body(*rows):
    return io.BytesIO(gzip.compress("\n".join(json.dumps(row) for row in rows).encode()))


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_copy_replaces_part_atomically_and_preserves_other_parts():
    first = {"musicbrainz_recording_id": MBID, "assignments": {"Q1": [EVIDENCE]}}
    second = {"musicbrainz_recording_id": OTHER, "assignments": {}}
    assert load_part(1, 0, body(first)) == 1
    assert load_part(1, 1, body(second)) == 1
    with pytest.raises(ValidationError):
        load_part(1, 0, body(second, {"musicbrainz_recording_id": "bad", "assignments": {}}))
    assert list(SongAssignmentStaging.objects.order_by("part").values_list("assignments", flat=True)) == [
        first["assignments"],
        second["assignments"],
    ]
    assert load_part(1, 0, body(second)) == 1
    assert list(SongAssignmentStaging.objects.order_by("part").values_list("assignments", flat=True)) == [{}, {}]
    with connection.cursor() as cursor:
        cursor.execute("SELECT relpersistence FROM pg_class WHERE oid = %s::regclass", ["grow_song_assignment_staging"])
        assert cursor.fetchone()[0] == "u"
