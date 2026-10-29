import hashlib
import json

import pytest
from rest_framework.exceptions import ValidationError

from grow.region_map.bulk_import.part_loader import _row, canonical_bytes

SHA256 = "0" * 64


def _line(document: str) -> bytes:
    return f'{{"path":"index.json","sha256":"{SHA256}","document":{document}}}'.encode()


@pytest.mark.parametrize(
    "document",
    ['{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":' + "[" * 1_000_000 + "]" * 1_000_000 + "}"],
    ids=["nan", "infinity", "negative-infinity", "deeply-nested"],
)
def test_non_json_line_rejected(document: str):
    with pytest.raises(ValidationError, match="line 1: invalid region map file"):
        _row(1, _line(document))


def test_number_overflowing_to_infinity_rejected():
    with pytest.raises(ValidationError, match="document is not serializable"):
        _row(1, _line('{"x":1e999}'))


def test_valid_line_then_path_and_sha256():
    document = {"type": "FeatureCollection", "features": []}
    sha256 = hashlib.sha256(canonical_bytes(document)).hexdigest()

    path, stored_sha256, _ = _row(1, json.dumps({"path": "a.json", "sha256": sha256, "document": document}).encode())

    assert (path, stored_sha256) == ("a.json", sha256)
