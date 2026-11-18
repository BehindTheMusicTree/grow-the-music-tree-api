"""Exercise trusted HTTP observations, artifact pinning and receipt ordering."""

import copy
import hashlib
import json
import os
import socketserver
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from benchmarks.catalogue import controller
from benchmarks.catalogue.manifest import Candidate, Session
from benchmarks.catalogue.performance_decision import decide
from benchmarks.catalogue.scenario_execution import HTTPScenario, UnixHTTPConnection
from benchmarks.catalogue.scenario_plan import canonical_bytes


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.paths.append(self.path)
        self.server.hosts.append(self.headers["Host"])
        self.send_response(self.server.status)
        self.send_header(
            "Content-Length", str(self.server.length if self.server.length is not None else len(self.server.content))
        )
        for name, value in self.server.extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(self.server.content)

    def log_message(self, *args):
        pass


class ControllerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        for name in (
            "benchmarks.catalogue.controller.private_path",
            "benchmarks.catalogue.controller.trusted_json",
            "benchmarks.catalogue.scenario_execution.trusted_json",
        ):
            guard = patch(
                name,
                side_effect=(lambda path: json.loads(path.read_text()))
                if name.endswith("trusted_json")
                else lambda *args, **kwargs: None,
            )
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch("benchmarks.catalogue.controller.os.geteuid", return_value=0)
        guard.start()
        self.addCleanup(guard.stop)
        self.policy = {
            "version": 1,
            "algorithm": "grow-paired-median-v1",
            "ratio": 1.3,
            "floor_ms": 5.0,
            "min_drift_scenarios": 10,
            "min_split_rounds": 2,
            "slo_ms": {"songs": 100000},
        }
        self.definition = {
            "version": 1,
            "path": "/songs/?page_size=2",
            "status": 200,
            "response_sha256": digest({"results": [1, 2], "count": 2}),
            "warmups": 1,
            "timeout_seconds": 1,
        }
        self.inventory = {
            "version": 1,
            "policy_sha256": digest(self.policy),
            "scenarios": [{"name": "songs", "requests": 2, "definition_sha256": digest(self.definition)}],
        }
        for name, value in (("inventory", self.inventory), ("policy", self.policy), ("songs", self.definition)):
            (self.artifacts / (name + ".json")).write_bytes(canonical_bytes(value))
        self.session = Session(
            "BehindTheMusicTree/grow-the-music-tree-api",
            1,
            Candidate("a" * 40, "ghcr.io/behindthemusictree/grow@sha256:" + "b" * 64),
            Candidate("c" * 40, "ghcr.io/behindthemusictree/grow@sha256:" + "d" * 64),
            "e" * 64,
            digest(self.inventory),
            4,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.content = b'{"count":2,"results":[1,2]}'
        self.server.status = 200
        self.server.paths = []
        self.server.hosts = []
        self.server.length = None
        self.server.extra_headers = []
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.worker.start()
        self.addCleanup(self.close_server)
        self.events = []
        self.cleanup_fails = False

    def close_server(self):
        self.server.shutdown()
        self.worker.join(timeout=5)
        self.server.server_close()

    @contextmanager
    def prepare(self, candidate, number):
        self.events.append(("prepare", candidate.sha, number))
        try:
            yield controller.Endpoint("127.0.0.1", self.server.server_port)
        finally:
            self.events.append(("close", candidate.sha, number))
            if self.cleanup_fails:
                raise RuntimeError("runtime cleanup failed")

    def execute(self):
        return controller.execute(self.session, "f" * 32, self.artifacts, self, lambda: None)

    def produce_receipt(self):
        return controller.run(self.session, "f" * 32, self.artifacts, self, lambda: None, self.root)

    def test_real_http_observations_bind_schedule_candidates_and_warmups(self):
        evidence = self.execute()
        self.assertEqual(len(self.server.paths), 24)
        self.assertEqual(set(self.server.paths), {self.definition["path"]})
        self.assertEqual(set(self.server.hosts), {"grow-perf.invalid"})
        self.assertEqual(
            self.events,
            [
                (action, getattr(self.session, side).sha, number)
                for side, number in self.session.schedule()
                for action in ("prepare", "close")
            ],
        )
        self.assertEqual(len(evidence["measurements"]), 8)
        self.assertTrue(all(len(row["latency_ms"]) == 2 for row in evidence["measurements"]))
        self.assertEqual(evidence["decision"], decide(evidence, self.session))

    @unittest.skipUnless(hasattr(os, "O_PATH"), "requires Linux pinned Unix sockets")
    def test_real_unix_http_observations_follow_the_controller_schedule(self):
        with tempfile.TemporaryDirectory(prefix="gp-") as temporary:
            path = Path(temporary) / "api.sock"
            with socketserver.UnixStreamServer(str(path), Handler) as server:
                for name in ("content", "status", "paths", "hosts", "length", "extra_headers"):
                    setattr(server, name, getattr(self.server, name))
                worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
                worker.start()

                @contextmanager
                def prepare(candidate, number):
                    yield controller.Endpoint("127.0.0.1", 1, path)

                try:
                    with patch.object(self, "prepare", prepare):
                        evidence = self.execute()
                    self.assertEqual(len(server.paths), 24)
                    self.assertEqual(len(evidence["measurements"]), 8)
                finally:
                    server.shutdown()
                    worker.join(timeout=5)

    def test_unix_http_rejects_unusable_paths_and_closes_failed_connections(self):
        for path in (Path("relative.sock"), Path("/" + "a" * 104)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                UnixHTTPConnection(path, 1)
        connection = UnixHTTPConnection(self.root / "absent.sock", 1)
        expected = FileNotFoundError if hasattr(os, "O_PATH") else RuntimeError
        with self.assertRaises(expected):
            connection.connect()
        self.assertIsNone(connection.sock)

    def test_receipt_digest_names_the_actual_durable_evidence(self):
        # Performance is tested deterministically below; here allow actual local
        # HTTP samples without asserting that laptop scheduling is stable.
        with patch("benchmarks.catalogue.controller.decide", return_value={"status": "passed"}):
            receipt = self.produce_receipt()
        value = json.loads(receipt.read_text())
        evidence = Path(value["evidence"])
        self.assertEqual(value["evidence_sha256"], hashlib.sha256(evidence.read_bytes()).hexdigest())
        self.assertEqual(value["identity"], self.session.identity)
        self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            self.produce_receipt()

    def test_tampered_artifacts_refuse_before_starting_any_candidate(self):
        for name in ("inventory", "policy", "songs"):
            path = self.artifacts / (name + ".json")
            original = path.read_bytes()
            value = json.loads(original)
            value["version"] = 2
            path.write_bytes(canonical_bytes(value))
            with self.subTest(artifact=name), self.assertRaises(ValueError):
                self.execute()
            self.assertEqual(self.events, [])
            path.write_bytes(original)

    def test_wrong_results_non_json_duplicate_keys_and_redirect_never_produce_receipt(self):
        for content, status in (
            (b"{}", 200),
            (b"not json", 200),
            (b'{"count":2,"count":2}', 200),
            (b'{"x":NaN}', 200),
            (self.server.content, 302),
        ):
            self.server.content, self.server.status = content, status
            with self.subTest(content=content, status=status), self.assertRaises(ValueError):
                self.execute()
            self.assertEqual(self.events[-1][0], "close")

    def test_failed_cleanup_and_supervision_never_produce_receipt(self):
        self.cleanup_fails = True
        with self.assertRaisesRegex(RuntimeError, "cleanup"):
            self.produce_receipt()
        self.assertFalse(list(self.root.rglob("receipt.json")))
        self.cleanup_fails = False

        def interrupted():
            raise RuntimeError("production preemption")

        with self.assertRaisesRegex(RuntimeError, "preemption"):
            controller.execute(self.session, "f" * 32, self.artifacts, self, interrupted)
        self.assertFalse(list(self.root.rglob("receipt.json")))

    def test_truncated_or_ambiguous_http_framing_cannot_produce_receipt(self):
        for length, extra in (
            (999, []),
            (None, [("Content-Length", "999")]),
            (None, [("Transfer-Encoding", "chunked")]),
        ):
            self.server.length, self.server.extra_headers = length, extra
            invocation = f"{len(self.events):032x}"
            with self.subTest(length=length, extra=extra), self.assertRaises(ValueError):
                controller.run(self.session, invocation, self.artifacts, self, lambda: None, self.root)
            self.assertEqual(self.events[-1][0], "close")
            self.assertFalse(list(self.root.rglob("receipt.json")))

    def test_regression_or_noise_retains_evidence_without_a_passing_receipt(self):
        for number, status in enumerate(("failed", "inconclusive")):
            invocation = f"{number:032x}"
            with (
                patch("benchmarks.catalogue.controller.decide", return_value={"status": status}),
                self.assertRaises(controller.BenchmarkRejected),
            ):
                controller.run(self.session, invocation, self.artifacts, self, lambda: None, self.root)
            self.assertTrue((self.root / invocation / "evidence.json").is_file())
            self.assertFalse((self.root / invocation / "receipt.json").exists())

    def test_invalid_scenario_definitions_are_refused(self):
        for key, value in (
            ("version", True),
            ("path", "//example.com/x"),
            ("path", "/x\r\nHost:x"),
            ("path", "/x#fragment"),
            ("warmups", 0),
            ("timeout_seconds", True),
            ("status", 302),
            ("response_sha256", "invalid"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                HTTPScenario.parse(dict(self.definition, **{key: value}))

    def test_paired_regression_slo_and_unstable_rounds(self):
        evidence = self.execute()
        for row in evidence["measurements"]:
            row["latency_ms"] = [100.0, 100.0]
        self.assertEqual(decide(evidence, self.session)["status"], "passed")
        slow = copy.deepcopy(evidence)
        for row in slow["measurements"]:
            if row["side"] == "head":
                row["latency_ms"] = [150.0, 150.0]
        result = decide(slow, self.session)
        self.assertEqual(result["status"], "failed")
        self.assertIn("regression", result["scenarios"][0]["reasons"])
        noisy = copy.deepcopy(evidence)
        for row in noisy["measurements"]:
            if row["side"] == "head" and row["round"] >= 3:
                row["latency_ms"] = [150.0, 150.0]
        self.assertEqual(decide(noisy, self.session)["status"], "inconclusive")
        slo = copy.deepcopy(evidence)
        for row in slo["measurements"]:
            row["latency_ms"] = [200000.0, 200000.0]
        self.assertIn("slo_breach", decide(slo, self.session)["scenarios"][0]["reasons"])

    def test_single_outlier_does_not_split_four_rounds(self):
        evidence = self.execute()
        for row in evidence["measurements"]:
            row["latency_ms"] = [100.0, 100.0]
            if row["side"] == "head" and row["round"] == 4:
                row["latency_ms"] = [200.0, 200.0]
        self.assertEqual(decide(evidence, self.session)["status"], "passed")
