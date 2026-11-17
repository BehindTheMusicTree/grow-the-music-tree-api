"""Pinned Grow policy distinguishes common drift from repeated plan splits."""

import copy
import hashlib
import sys
import unittest
from pathlib import Path

from benchmarks.catalogue.manifest import Candidate, Session
from benchmarks.catalogue.performance_decision import Policy, decide
from benchmarks.catalogue.scenario_plan import ScenarioPlan, canonical_bytes


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class DecisionTest(unittest.TestCase):
    def setUp(self):
        self.names = ["scenario_" + str(i) for i in range(10)]
        self.policy = {
            "version": 1,
            "algorithm": "grow-paired-median-v1",
            "ratio": 1.3,
            "floor_ms": 5,
            "min_drift_scenarios": 10,
            "min_split_rounds": 2,
            "slo_ms": dict.fromkeys(self.names, 1000),
        }
        inventory = {
            "version": 1,
            "policy_sha256": digest(self.policy),
            "scenarios": [{"name": name, "requests": 2, "definition_sha256": "a" * 64} for name in self.names],
        }
        candidate = Candidate("b" * 40, "ghcr.io/behindthemusictree/grow@sha256:" + "c" * 64)
        self.session = Session(
            "BehindTheMusicTree/grow-the-music-tree-api", 1, candidate, candidate, "d" * 64, digest(inventory), 4
        )
        self.evidence = {
            "scenario_plan": inventory,
            "comparison_policy": self.policy,
            "scenarios": self.names,
            "measurements": [
                {
                    "side": side,
                    "round": number,
                    "scenario": name,
                    "sha": candidate.sha,
                    "image": candidate.image,
                    "requests": 2,
                    "errors": 0,
                    "correct": True,
                    "latency_ms": [100.0, 100.0],
                }
                for side, number in self.session.schedule()
                for name in self.names
            ],
        }

    def test_common_drift_does_not_look_like_scenario_plan_splits(self):
        for row in self.evidence["measurements"]:
            if row["round"] >= 3:
                row["latency_ms"] = [200.0, 200.0]
        result = decide(self.evidence, self.session)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["drift"]["base"], [2 / 3, 2 / 3, 4 / 3, 4 / 3])
        self.assertTrue(all(row["ratio"] == 1 for row in result["scenarios"]))

    def test_repeated_single_scenario_split_is_inconclusive(self):
        for row in self.evidence["measurements"]:
            if row["side"] == "head" and row["round"] >= 3 and row["scenario"] == self.names[0]:
                row["latency_ms"] = [200.0, 200.0]
        result = decide(self.evidence, self.session)
        self.assertEqual(result["status"], "inconclusive")
        self.assertIn("unstable_head", result["scenarios"][0]["reasons"])
        self.assertTrue(all(row["reasons"] == [] for row in result["scenarios"][1:]))

    def test_regression_requires_both_ratio_and_absolute_floor(self):
        for base, head in ((1, 2), (100, 110)):
            for row in self.evidence["measurements"]:
                row["latency_ms"] = [base if row["side"] == "base" else head] * 2
            self.assertEqual(decide(self.evidence, self.session)["status"], "passed")

    def test_invalid_policy_cannot_pass_even_when_its_hash_is_pinned(self):
        for key, value in (
            ("version", True),
            ("algorithm", "candidate-script"),
            ("ratio", 1),
            ("ratio", True),
            ("floor_ms", 0),
            ("min_drift_scenarios", 1),
            ("min_split_rounds", 1),
            ("slo_ms", {}),
        ):
            policy = dict(self.policy, **{key: value})
            inventory = dict(self.evidence["scenario_plan"], policy_sha256=digest(policy))
            plan = ScenarioPlan.parse(inventory, digest(inventory))
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                Policy.parse(policy, plan)

    def test_missing_or_failed_coverage_precedes_performance_decision(self):
        value = copy.deepcopy(self.evidence)
        value["measurements"].pop()
        with self.assertRaises(ValueError):
            decide(value, self.session)
        value = copy.deepcopy(self.evidence)
        value["measurements"][0]["correct"] = False
        with self.assertRaises(ValueError):
            decide(value, self.session)
