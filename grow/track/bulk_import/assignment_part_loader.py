import json
import uuid
from typing import IO

from rest_framework.exceptions import ValidationError
from the_music_tree_genre_graph import GraphValidationError
from the_music_tree_genre_kit.genre_graph.assignments import validate_evidence

from grow.bulk_import.copy_part import copy_part
from grow.genre_graph.service import validate_song_attributions
from grow.track.bulk_import.SongAssignmentStaging import SongAssignmentStaging

COLUMNS = ("musicbrainz_recording_id", "assignments")


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _row(line_number: int, line: bytes) -> tuple:
    try:
        row = json.loads(line, object_pairs_hook=_object)
        if not isinstance(row, dict) or set(row) != set(COLUMNS):
            raise ValueError("expected musicbrainz_recording_id and assignments")
        recording = row["musicbrainz_recording_id"]
        if not isinstance(recording, str):
            raise ValueError("musicbrainz_recording_id must be a UUID")
        uuid.UUID(recording)
        assignments = row["assignments"]
        validate_song_attributions(assignments)
        decisions = {}
        for identity, evidence in assignments.items():
            if not isinstance(identity, str) or not identity.strip() or not isinstance(evidence, list) or not evidence:
                raise ValueError("each identity requires a nonempty evidence list")
            seen = set()
            for item in evidence:
                item = validate_evidence(item)
                decision_id = item["decisionId"]
                if decision_id in seen:
                    raise ValueError("duplicate evidence for an identity")
                if decision_id in decisions and decisions[decision_id] != item:
                    raise ValueError("conflicting evidence for a decisionId")
                seen.add(decision_id)
                decisions[decision_id] = item
    except (ValueError, TypeError, GraphValidationError) as error:
        raise ValidationError(f"line {line_number}: invalid assignment ({error})") from error
    return recording, json.dumps(assignments)


def load_part(run_id: int, part: int, body: IO[bytes]) -> int:
    return copy_part(SongAssignmentStaging, COLUMNS, _row, run_id, part, body)
