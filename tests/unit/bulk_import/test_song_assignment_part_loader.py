import json

import pytest
from rest_framework.exceptions import ValidationError

from grow.track.bulk_import.assignment_part_loader import _row

MBID = "b1a9c0e9-d987-4042-ae91-78d6a3267d69"
EVIDENCE = {"decisionId": "decision-1", "source": "curation", "rationale": "Reviewed"}


def row(assignments):
    return {"musicbrainz_recording_id": MBID, "assignments": assignments}


@pytest.mark.parametrize(
    "assignments", [{}, {"Q1": [EVIDENCE]}, {"LOCAL:regional": [EVIDENCE, {**EVIDENCE, "decisionId": "second"}]}]
)
def test_valid_complete_assignment_sets(assignments):
    recording, encoded = _row(1, json.dumps(row(assignments)).encode())
    assert recording == MBID
    assert json.loads(encoded) == assignments


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"musicbrainz_recording_id": "bad", "assignments": {}},
        row(None),
        row({"Q1": [EVIDENCE], "Q2": [EVIDENCE]}),
        row({"Q1": []}),
        row({" ": [EVIDENCE]}),
        row({"Q1": [{"decisionId": "x"}]}),
        row({"Q1": [EVIDENCE, EVIDENCE]}),
        row({"Q1": [EVIDENCE], "Q2": [{**EVIDENCE, "source": "different"}]}),
    ],
)
def test_invalid_assignment_rows_are_rejected(value):
    with pytest.raises(ValidationError, match="line 7"):
        _row(7, json.dumps(value).encode())


@pytest.mark.parametrize(
    "raw",
    [
        '{"musicbrainz_recording_id": "' + MBID + '", "assignments": {}, "assignments": {}}',
        '{"musicbrainz_recording_id": "' + MBID + '", "assignments": {"Q1": [], "Q1": []}}',
        '{"musicbrainz_recording_id": "' + MBID + '", "assignments": {"Q1": [{"decisionId": "a", "decisionId": "b"}]}}',
    ],
)
def test_duplicate_json_keys_cannot_silently_discard_assignments_or_evidence(raw):
    with pytest.raises(ValidationError, match="duplicate object key"):
        _row(1, raw.encode())
