"""Gold → grow genre tree contract, checked against the pipelines' published JSON Schema.

Run with `GOLD_SCHEMA_PATH=<genre_tree.schema.json> pytest -m contract --no-cov`. The schema is the pipelines'
`pipelines/gold/src/gold/schemas/genre_tree.schema.json`; CI fetches it from the matching pipelines branch.
"""

import json
import os
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.serializer import (
    CriteriaTreeImportSerializer,
)
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_node import CriteriaTreeNodeSerializer

from tests.utils.AppTestCase import AppTestCase
from tests.utils.curation_export import export_curation

pytestmark = pytest.mark.contract

# Written by grow's import, never by the tree serializer: popped from each entry before validation.
POPPED_BY_GROW = {"curationExportedOn"}

IMAGE = {
    "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/Example.jpg",
    "pageUrl": "https://commons.wikimedia.org/wiki/File:Example.jpg",
    "author": "Jane Doe",
    "license": "CC BY-SA 4.0",
    "licenseUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
}

# Every property of the schema appears at least once across the two files (checked by test_sample_covers_schema).
CANONICAL_NODES = [
    {
        "id": "Q1001",
        "name": "Contract pop",
        "side": "pop",
        "isUmbrella": True,
        "summary": "A genre used to exercise the contract.",
        "summarySourceUrl": "https://en.wikipedia.org/wiki/Pop_music",
        "description": "A longer description of the genre.",
        "image": IMAGE,
        "children": [
            {
                "id": "Q1002",
                "name": "Contract scene split",
                "children": [
                    {"id": "Q1003", "name": "Contract commercial", "scene": "commercial", "children": []},
                    {"id": "Q1004", "name": "Contract underground", "scene": "underground", "children": []},
                ],
            },
            {"id": "Q1005", "name": "Contract sibling", "primaryParents": ["Q1001"], "children": []},
            {"id": "Q1006", "name": "Contract secondary", "secondaryParents": ["Q1005"], "children": []},
        ],
    },
    {"id": "Q1007", "name": "Contract unaccepted", "isUnacceptedRoot": True, "children": []},
]
REGIONAL_NODES = [
    {"id": "Q2001", "name": "Contract region", "children": [{"id": "Q2002", "name": "Contract local", "children": []}]}
]


def _tree_files(exported_on: str) -> list[dict]:
    return [
        {"treeName": "canonical", "curationExportedOn": exported_on, "tree": CANONICAL_NODES},
        {
            "treeName": "regional",
            "curationExportedOn": exported_on,
            "tree": REGIONAL_NODES,
            "crossTreeSecondaryParents": [{"id": "Q2002", "secondaryParents": ["Q1005"]}],
        },
    ]


@pytest.fixture(scope="module")
def schema() -> dict:
    path = os.environ.get("GOLD_SCHEMA_PATH")
    if not path:
        raise RuntimeError("GOLD_SCHEMA_PATH is not set: point it at the pipelines genre_tree.schema.json")
    return json.loads(Path(path).read_text())


def _walk_nodes(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from _walk_nodes(node.get("children", []))


def _keys_used(files: list[dict]) -> dict[str, set[str]]:
    nodes = [n for f in files for n in _walk_nodes(f["tree"])]
    return {
        "file": {key for f in files for key in f},
        "node": {key for n in nodes for key in n},
        "image": {key for n in nodes for key in n.get("image", {})},
        "cross": {key for f in files for item in f.get("crossTreeSecondaryParents", []) for key in item},
    }


def _keys_declared(schema: dict) -> dict[str, set[str]]:
    cross = schema["properties"]["crossTreeSecondaryParents"]["items"]["properties"]
    node = schema["$defs"]["node"]["properties"]
    return {
        "file": set(schema["properties"]),
        "node": set(node),
        "image": set(node["image"]["properties"]),
        "cross": set(cross),
    }


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _grow_fields(serializer) -> dict[str, bool]:
    """Wire name (camelCase) → required, from grow's own input serializer."""
    return {_camel(name): field.required for name, field in serializer.fields.items()}


def test_sample_covers_schema(schema):
    used, declared = _keys_used(_tree_files("2026-01-01T00:00:00Z")), _keys_declared(schema)

    assert used == declared, {k: {"unused": declared[k] - used[k], "unknown": used[k] - declared[k]} for k in used}


def test_grow_accepts_every_schema_property(schema):
    declared = _keys_declared(schema)
    file_fields = _grow_fields(CriteriaTreeImportSerializer())
    node_fields = _grow_fields(CriteriaTreeNodeSerializer(structure_field_name="tree"))

    assert declared["file"] - POPPED_BY_GROW <= set(file_fields)
    assert declared["node"] <= set(node_fields)


def test_grow_required_fields_are_required_by_schema(schema):
    file_required = {k for k, required in _grow_fields(CriteriaTreeImportSerializer()).items() if required}
    node_required = {
        k for k, required in _grow_fields(CriteriaTreeNodeSerializer(structure_field_name="tree")).items() if required
    }

    assert file_required <= set(schema["required"])
    assert node_required <= set(schema["$defs"]["node"]["required"])


class TestGoldTreeContractEndToEnd(AppTestCase):
    def test_batch_of_gold_files_as_the_pipeline_posts_them_then_imported(self):
        pipeline = APIClient()
        pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)
        url = reverse("genre-list") + "trees/import-runs/"

        response = pipeline.post(url, data={"trees": _tree_files(export_curation(pipeline))}, format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED, response.content
        polled = pipeline.get(reverse("genre-list") + f"trees/import/{response.json()['taskId']}/status/").json()
        assert polled["status"] == "success", polled
