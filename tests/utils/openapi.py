import gzip
import json
from functools import cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry

ROOT = Path(__file__).resolve().parents[2]


def wire_fixture(name):
    return json.loads((ROOT / "tests/fixtures/openapi" / f"{name}.json").read_text(encoding="utf-8"))


@cache
def committed_schema():
    return yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))


def wire_validator(document, fragment):
    return Draft202012Validator(
        {**document, "allOf": [fragment]}, registry=Registry(), format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def assert_response_matches_schema(response, path, method="get"):
    schema = committed_schema()
    definition = schema["paths"][path][method]["responses"][str(response.status_code)]
    if "content" not in definition:
        assert not response.content
        return None
    media = response.headers["Content-Type"].split(";", 1)[0]
    data = (
        json.loads(gzip.decompress(response.content))
        if response.headers.get("Content-Encoding") == "gzip"
        else response.json()
    )
    wire_validator(schema, definition["content"][media]["schema"]).validate(data)
    return data
