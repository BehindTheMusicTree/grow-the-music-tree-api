import gzip
import hashlib
import json
import re
from typing import IO, Any

from rest_framework.exceptions import ValidationError

from grow.bulk_import.copy_part import copy_part
from grow.region_map.bulk_import.RegionMapFileStaging import RegionMapFileStaging

SHA256 = re.compile(r"[0-9a-f]{64}")
# The unique (snapshot, path) btree key must stay under ~2.7 kB.
PATH_LEN_MAX = 512  # bytes


def canonical_bytes(document: Any) -> bytes:
    """The bytes a region map file's sha256 is taken over, as the pipeline serializes them."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _require(condition: bool, line_number: int, message: str) -> None:
    if not condition:
        raise ValidationError(f"line {line_number}: {message}")


def _row(line_number: int, line: bytes) -> tuple:
    try:
        entry = json.loads(line)
    except ValueError as e:
        raise ValidationError(f"line {line_number}: invalid region map file ({e})") from e
    _require(isinstance(entry, dict), line_number, "region map file must be an object")
    path = entry.get("path")
    _require(
        isinstance(path, str) and path != "" and len(path.encode()) <= PATH_LEN_MAX,
        line_number,
        f"path must be a non-empty string of at most {PATH_LEN_MAX} bytes",
    )
    sha256 = entry.get("sha256")
    _require(isinstance(sha256, str) and SHA256.fullmatch(sha256) is not None, line_number, "sha256 must be hex")
    _require(isinstance(entry.get("document"), dict), line_number, "document must be an object")
    canonical = canonical_bytes(entry["document"])
    _require(hashlib.sha256(canonical).hexdigest() == sha256, line_number, f"{path}: sha256 does not match document")
    return path, sha256, gzip.compress(canonical, mtime=0)


def load_part(run_id: int, part: int, body: IO[bytes]) -> int:
    return copy_part(RegionMapFileStaging, ("path", "sha256", "body"), _row, run_id, part, body)
