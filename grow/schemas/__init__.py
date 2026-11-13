"""JSON Schemas of the Gold exports grow imports (artist, genealogy, region map, hidden regions).

grow implements these imports, so it owns their contract; the pipelines repo vendors byte copies pinned to a release tag.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator
from jsonschema.protocols import Validator

SCHEMAS_DIR = Path(__file__).parent
GOLD_SCHEMA_NAMES = ("artist", "genealogy", "region_map", "hidden_regions")


def load_gold_schema(name: str) -> dict[str, Any]:
    if name not in GOLD_SCHEMA_NAMES:
        raise ValueError(f"unknown Gold schema {name!r}; expected one of {GOLD_SCHEMA_NAMES}")
    return json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


@cache
def gold_validator(name: str) -> Validator:
    """Validator for the schema's own draft: `genealogy` and `region_map` are draft-07, the others 2020-12."""
    schema = load_gold_schema(name)
    cls = Draft7Validator if schema["$schema"].startswith("http://json-schema.org/draft-07") else Draft202012Validator
    cls.check_schema(schema)
    return cls(schema)


def first_error(name: str, document: Any) -> str | None:
    """The most specific schema violation as `path: message`, or None when the document is valid."""
    error = next(iter(sorted(gold_validator(name).iter_errors(document), key=lambda e: list(e.absolute_path))), None)
    if error is None:
        return None
    return f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
