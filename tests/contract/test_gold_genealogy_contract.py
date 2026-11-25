"""Gold genealogy export: grow validates the document against its own JSON Schema at import time.

The sample is the integration test's document: every schema property appears in it, it is schema-valid, and grow stores it.
"""

from jsonschema import Draft7Validator
from the_music_tree_grow_contracts import load_schema

from tests.integration.genealogy.test_genealogy import DOCUMENT
from tests.utils.json_schema import keys_used, property_names


def test_sample_covers_every_schema_property():
    declared, used = property_names(load_schema("genealogy")), keys_used(DOCUMENT)

    assert declared == used, {"unused": declared - used, "unknown": used - declared}


def test_sample_is_schema_valid():
    Draft7Validator.check_schema(load_schema("genealogy"))

    assert Draft7Validator(load_schema("genealogy")).is_valid(DOCUMENT)
