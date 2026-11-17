"""A controller exit cannot substitute for durable, session-bound evidence."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.catalogue.manifest import Candidate, Session
from benchmarks.catalogue.performance_decision import decide
from benchmarks.catalogue.reporting import Report
from benchmarks.catalogue.scenario_plan import canonical_bytes


class ReportingTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Only filesystem ownership is mocked: the protocol and disk writes run.
        guard = patch("benchmarks.catalogue.reporting.private_path")
        guard.start()
        self.addCleanup(guard.stop)
        reader = patch(
            "benchmarks.catalogue.reporting.trusted_json",
            side_effect=lambda path, **kwargs: json.loads(path.read_text()),
        )
        reader.start()
        self.addCleanup(reader.stop)
        candidate = Candidate("a" * 40, "ghcr.io/behindthemusictree/grow@sha256:" + "b" * 64)
        policy = {
            "version": 1,
            "algorithm": "grow-paired-median-v1",
            "ratio": 1.3,
            "floor_ms": 5.0,
            "min_drift_scenarios": 10,
            "min_split_rounds": 2,
            "slo_ms": {"songs": 100},
        }
        plan = {
            "version": 1,
            "policy_sha256": hashlib.sha256(canonical_bytes(policy)).hexdigest(),
            "scenarios": [{"name": "songs", "requests": 1, "definition_sha256": "d" * 64}],
        }
        self.session = Session(
            "BehindTheMusicTree/grow-the-music-tree-api",
            1,
            candidate,
            candidate,
            "c" * 64,
            hashlib.sha256(canonical_bytes(plan)).hexdigest(),
            4,
        )
        self.report = Report(self.root, self.session)
        self.evidence = self.root / "original.json"
        self.evidence_value = {
            "scenario_plan": plan,
            "comparison_policy": policy,
            "version": 1,
            "manifest": self.session.as_dict(),
            "invocation": "e" * 32,
            "scenarios": ["songs"],
            "measurements": [
                {
                    "side": side,
                    "round": number,
                    "scenario": "songs",
                    "sha": candidate.sha,
                    "image": candidate.image,
                    "requests": 1,
                    "errors": 0,
                    "correct": True,
                    "latency_ms": [1.0],
                }
                for side, number in self.session.schedule()
            ],
        }
        self.evidence_value["decision"] = decide(self.evidence_value, self.session)
        self.evidence.write_text(json.dumps(self.evidence_value))
        self.receipt = self.root / "receipt.json"
        self.value = {
            "version": 1,
            "identity": self.session.identity,
            "invocation": "e" * 32,
            "status": "passed",
            "evidence": str(self.evidence),
            "evidence_sha256": hashlib.sha256(self.evidence.read_bytes()).hexdigest(),
        }

    def verify(self):
        self.receipt.write_text(json.dumps(self.value))
        return self.report.verify_execution(self.receipt, "e" * 32)

    def test_success_retains_evidence_after_original_is_deleted(self):
        self.verify()
        self.evidence.unlink()
        self.report.finish(passed=True, cleanup_acknowledged=True)
        persisted = json.loads((self.report.directory / "report.json").read_text())
        self.assertEqual(persisted["status"], "passed")
        self.assertEqual(
            hashlib.sha256(Path(persisted["evidence"]).read_bytes()).hexdigest(), persisted["evidence_sha256"]
        )

    def test_wrong_session_invocation_status_or_digest_cannot_pass(self):
        for key, value in (
            ("identity", "f" * 64),
            ("invocation", "f" * 32),
            ("status", "running"),
            ("evidence_sha256", "f" * 64),
        ):
            with self.subTest(key=key):
                self.report = Report(self.root, self.session)
                original = self.value[key]
                self.value[key] = value
                with self.assertRaises(ValueError):
                    self.verify()
                with self.assertRaises(ValueError):
                    self.report.finish(passed=True, cleanup_acknowledged=True)
                self.value[key] = original

    def test_evidence_must_bind_complete_manifest_and_invocation(self):
        other_manifest = dict(self.session.as_dict(), rounds=6)
        for key, value in (
            ("manifest", other_manifest),
            ("manifest", None),
            ("invocation", "f" * 32),
            ("version", True),
        ):
            with self.subTest(key=key, value=value):
                self.report = Report(self.root, self.session)
                altered = dict(self.evidence_value, **{key: value})
                self.evidence.write_text(json.dumps(altered))
                self.value["evidence_sha256"] = hashlib.sha256(self.evidence.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):
                    self.verify()
                with self.assertRaises(ValueError):
                    self.report.finish(passed=True, cleanup_acknowledged=True)

    def test_missing_failed_or_misattributed_measurements_cannot_pass(self):
        cases = [
            {"measurements": []},
            {"scenarios": []},
            {"scenario_plan": None},
            {"comparison_policy": None},
            {"comparison_policy": dict(self.evidence_value["comparison_policy"], ratio=2)},
            {"decision": {"status": "passed"}},
            {"scenario_plan": dict(self.evidence_value["scenario_plan"], policy_sha256="a" * 64)},
        ]
        for key, bad in (
            ("round", True),
            ("sha", "f" * 40),
            ("errors", 1),
            ("correct", False),
            ("requests", 2),
            ("latency_ms", [float("nan")]),
            ("latency_ms", [True]),
        ):
            rows = copy.deepcopy(self.evidence_value["measurements"])
            rows[0][key] = bad
            cases.append({"measurements": rows})
        for change in cases:
            with self.subTest(change=change):
                self.report = Report(self.root, self.session)
                self.evidence.write_text(json.dumps(dict(self.evidence_value, **change)))
                self.value["evidence_sha256"] = hashlib.sha256(self.evidence.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):
                    self.verify()
                with self.assertRaises(ValueError):
                    self.report.finish(passed=True, cleanup_acknowledged=True)

    def test_exit_without_evidence_and_cleanup_cannot_pass(self):
        with self.assertRaises(ValueError):
            self.report.finish(passed=True, cleanup_acknowledged=True)
        self.verify()
        with self.assertRaises(ValueError):
            self.report.finish(passed=True, cleanup_acknowledged=False)

    def test_forged_passing_decision_cannot_hide_observed_regression(self):
        for row in self.evidence_value["measurements"]:
            row["latency_ms"] = [100.0 if row["side"] == "head" else 1.0]
        self.evidence.write_text(json.dumps(self.evidence_value))
        self.value["evidence_sha256"] = hashlib.sha256(self.evidence.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "performance decision"):
            self.verify()
        with self.assertRaises(ValueError):
            self.report.finish(passed=True, cleanup_acknowledged=True)

    def test_failed_write_keeps_running_record_and_allows_interruption(self):
        with (
            patch.object(Path, "replace", side_effect=OSError("disk failure")),
            self.assertRaises(OSError),
        ):
            self.report.finish(passed=False, cleanup_acknowledged=False, cause="failure")
        self.assertEqual(self.report.value["status"], "running")
        self.assertFalse((self.report.directory / "report.pending.json").exists())
        self.report.finish(passed=False, cleanup_acknowledged=False, cause="failure")
        with self.assertRaises(RuntimeError):
            self.report.finish(passed=False, cleanup_acknowledged=False)

    def test_same_manifest_uses_unique_report_directories(self):
        other = Report(self.root, self.session)
        self.assertNotEqual(other.directory, self.report.directory)
