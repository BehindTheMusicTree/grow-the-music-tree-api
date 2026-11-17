"""The admitted inventory prevents dropping scenarios or changing policy."""

import copy
import hashlib
import sys
import unittest
from pathlib import Path

from benchmarks.catalogue.scenario_plan import ScenarioPlan, canonical_bytes


class ScenarioPlanTest(unittest.TestCase):
    def setUp(self):
        self.value = {
            "version": 1,
            "policy_sha256": "a" * 64,
            "scenarios": [{"name": "songs", "requests": 10, "definition_sha256": "b" * 64}],
        }
        self.digest = hashlib.sha256(canonical_bytes(self.value)).hexdigest()

    def test_immutable_inventory(self):
        plan = ScenarioPlan.parse(self.value, self.digest)
        self.assertEqual(plan.names, ("songs",))
        self.assertEqual(plan.requests, (10,))
        self.assertEqual(plan.policy_sha256, "a" * 64)

    def test_altered_inventory_cannot_use_original_identity(self):
        for field, altered in (("name", "search"), ("requests", 1), ("definition_sha256", "c" * 64)):
            value = copy.deepcopy(self.value)
            value["scenarios"][0][field] = altered
            with self.subTest(field=field), self.assertRaises(ValueError):
                ScenarioPlan.parse(value, self.digest)

    def test_invalid_inventory_is_rejected_even_with_matching_hash(self):
        values = [
            dict(self.value, version=True),
            dict(self.value, scenarios=[]),
            dict(self.value, scenarios=self.value["scenarios"] * 2),
            dict(self.value, policy_sha256="invalid"),
        ]
        for count in (True, 0, -1, 10001, 1.5):
            value = copy.deepcopy(self.value)
            value["scenarios"][0]["requests"] = count
            values.append(value)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ScenarioPlan.parse(value, hashlib.sha256(canonical_bytes(value)).hexdigest())
