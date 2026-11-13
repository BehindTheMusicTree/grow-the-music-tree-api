"""Gold region map export (index, hidden regions, synthesized overview alerts): grow validates each file against its
own JSON Schema at import time.

The samples are the integration test's documents, with one fully populated region: every schema property appears in them,
they are schema-valid, and grow stores them.
"""

import pytest
from jsonschema import Draft7Validator

from grow.schemas import load_gold_schema
from tests.integration.region_map.test_region_map import ALERT, GENRE, HIDDEN, TRADITION, _index, _region
from tests.utils.json_schema import keys_used, property_names

FULL_REGION = _region(
    "Q142",
    isoCode="FR",
    childIds=["Q90"],
    zoneIds=["Q91"],
    cityIds=["Q90"],
    mainBbox=[0, 0, 1, 1],
    genres=[{"itemId": GENRE, "relation": "canonical"}, {"itemId": TRADITION, "relation": "tradition"}],
)
SAMPLES = {
    "region_map": _index(
        [
            FULL_REGION,
            _region("Q90", kind="city", parentId="Q142"),
            _region("Q91", kind="zone", parentId="Q142"),
        ],
        worldChildIds=["Q142"],
        worldZoneIds=["Q91"],
    ),
    "hidden_regions": {"regions": [HIDDEN]},
    "synthesized_overview_alerts": {"alerts": [ALERT]},
}


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_covers_every_schema_property(name):
    declared, used = property_names(load_gold_schema(name)), keys_used(SAMPLES[name])

    assert declared == used, {"unused": declared - used, "unknown": used - declared}


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_is_schema_valid(name):
    Draft7Validator.check_schema(load_gold_schema(name))

    assert Draft7Validator(load_gold_schema(name)).is_valid(SAMPLES[name])
