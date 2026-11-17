"""Hosted runtime and verdict: forged provenance, isolation drift, cleanup, deadline, evidence."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.catalogue import hosted, hosted_runtime
from benchmarks.catalogue.database_handoff import ROLE_PROOF_SQL
from benchmarks.catalogue.manifest import HostedSession, Session
from benchmarks.catalogue.scenario_plan import canonical_bytes

REPOSITORY = "BehindTheMusicTree/grow-the-music-tree-api"
INVOCATION = "e" * 32
PREPARE = b"print('prepare')\n"
SETTINGS = b"SETTINGS = 1\n"
POSTGRES = "docker.io/library/postgres@sha256:" + "a" * 64
BASE_IMAGE = "ghcr.io/behindthemusictree/grow@sha256:" + "b" * 64
HEAD_IMAGE = "ghcr.io/behindthemusictree/grow@sha256:" + "c" * 64


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def raw_manifest(**changes):
    value = {
        "version": 2,
        "repository": REPOSITORY,
        "pull_request": 7,
        "base": {"sha": "1" * 40, "image": BASE_IMAGE},
        "head": {"sha": "2" * 40, "image": HEAD_IMAGE},
        "catalogue_sha256": "3" * 64,
        "scenario_sha256": "4" * 64,
        "policy_sha256": "5" * 64,
        "postgres_image": POSTGRES,
        "preparation": {"version": 1, "script_sha256": digest(PREPARE), "settings_sha256": digest(SETTINGS)},
        "runner": "4cpu-16gb",
        "deadline": "2099-01-01T00:00:00Z",
        "rounds": 4,
    }
    value.update(changes)
    return value


class ManifestTest(unittest.TestCase):
    def test_version_two_parses_into_a_hosted_session(self):
        session = Session.parse(raw_manifest())
        self.assertIsInstance(session, HostedSession)
        self.assertEqual(session.as_dict(), raw_manifest())
        self.assertEqual(session.backup_sha256, "3" * 64)

    def test_identity_binds_every_hosted_field(self):
        identity = Session.parse(raw_manifest()).identity
        for changes in (
            {"runner": "8cpu-32gb"},
            {"deadline": "2099-01-01T00:00:01Z"},
            {"policy_sha256": "6" * 64},
            {"postgres_image": "docker.io/library/postgres@sha256:" + "d" * 64},
        ):
            self.assertNotEqual(Session.parse(raw_manifest(**changes)).identity, identity)

    def test_malformed_hosted_manifests_are_rejected(self):
        for changes in (
            {"runner": "2cpu-8gb"},
            {"deadline": "tomorrow"},
            {"deadline": "2099-13-45T00:00:00Z"},
            {"postgres_image": "docker.io/library/postgres:16"},
            {"rounds": 3},
            {"repository": "other/repo"},
            {"head": {"sha": "1" * 40, "image": HEAD_IMAGE}},
            {"extra": 1},
        ):
            with self.assertRaises(ValueError, msg=str(changes)):
                Session.parse(raw_manifest(**changes))

    def test_version_one_still_parses(self):
        candidate = {"sha": "1" * 40, "image": BASE_IMAGE}
        session = Session.parse(
            {
                "version": 1,
                "repository": REPOSITORY,
                "pull_request": 1,
                "base": candidate,
                "head": {"sha": "2" * 40, "image": HEAD_IMAGE},
                "backup_sha256": "3" * 64,
                "scenario_sha256": "4" * 64,
                "rounds": 4,
            }
        )
        self.assertNotIsInstance(session, HostedSession)


class FakeDocker:
    """Just enough Docker semantics to exercise the runtime's verification."""

    def __init__(self, session):
        self.session = session
        self.containers: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.tamper: dict = {}
        self.repo_digests = {
            "b" * 64: [BASE_IMAGE],
            "c" * 64: [HEAD_IMAGE],
            "a" * 64: ["postgres@sha256:" + "a" * 64],
        }
        self.fail_rm = False
        self.leak = False

    def local(self, reference):
        return reference.rsplit(":", 1)[1] * 1

    def __call__(self, *args, stdin=None, timeout=30):
        self.calls.append(args)
        verb = args[0]
        if verb == "image":
            key = args[2].rsplit(":", 1)[1]
            digests = self.tamper.get("RepoDigests", self.repo_digests[key])
            return json.dumps([{"Id": "sha256:" + key, "RepoDigests": digests, "Config": {"Volumes": None}}])
        if verb == "create":
            return self.create(args)
        if verb == "inspect":
            return self.inspect(args)
        if verb == "start":
            # The preparation job is one-shot: it has already exited when polled.
            self.containers[args[1]]["running"] = not self.containers[args[1]]["oneshot"]
            return args[1]
        if verb == "stop":
            self.containers[args[3]]["running"] = False
            return args[3]
        if verb == "rm":
            if self.fail_rm:
                raise subprocess.CalledProcessError(1, "docker rm")
            self.containers = {k: v for k, v in self.containers.items() if v["name"] != args[-1] and k != args[-1]}
            return args[-1]
        if verb == "ps":
            filter_ = args[-1]
            if self.leak and filter_.startswith("label="):
                return "f" * 64
            return "\n".join(
                key for key, value in self.containers.items() if value["name"] in filter_ or "label=" in filter_
            )
        if verb == "exec":
            return self.execute(args, stdin)
        raise AssertionError(args)

    def create(self, args):
        name = args[args.index("--name") + 1]
        user = args[args.index("--user") + 1]
        image = args[args.index("--entrypoint") + 2]
        mounts, tmpfs = [], []
        for index, item in enumerate(args):
            if item == "--mount":
                fields = dict(
                    part.split("=", 1) if "=" in part else (part, True) for part in args[index + 1].split(",")
                )
                mounts.append(
                    {
                        "Type": "bind",
                        "Source": fields["src"],
                        "Destination": fields["dst"],
                        "RW": "readonly" not in fields,
                    }
                )
            if item == "--tmpfs":
                tmpfs.append(args[index + 1].split(":", 1)[0])
        identity = hashlib.sha256(name.encode()).hexdigest()
        hba = next((m["Source"] for m in mounts if m["Destination"] == "/approved/pg_hba.conf"), None)
        host = {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "PidMode": "",
            "IpcMode": "private",
            "Memory": int(args[args.index("--memory") + 1]),
            "MemorySwap": int(args[args.index("--memory-swap") + 1]),
            "PidsLimit": int(args[args.index("--pids-limit") + 1]),
            "NanoCpus": int(args[args.index("--cpus") + 1]) * 10**9,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": dict.fromkeys(tmpfs, ""),
            "Binds": None,
            "Devices": None,
        }
        host.update(self.tamper.get("HostConfig", {}))
        self.containers[identity] = {
            "name": name,
            "oneshot": "/approved/prepare.py" in args,
            "running": False,
            "hba": hba,
            "details": {
                "Image": image,
                "Config": {"User": user, "Labels": {hosted_runtime.LABEL: INVOCATION}},
                "HostConfig": host,
                "Mounts": mounts + [{"Type": "tmpfs", "Destination": path} for path in tmpfs],
                "State": {"Pid": 4242, "Running": False},
            },
        }
        return identity

    def inspect(self, args):
        container = self.containers[args[-1]]
        if len(args) == 3:
            template = args[1]
            if "ExitCode" in template:
                return "0"
            return "true" if container["running"] else "false"
        details = copy.deepcopy(container["details"])
        details["State"]["Running"] = container["running"] or container["oneshot"]
        return json.dumps([details])

    def execute(self, args, stdin):
        identity = args[args.index("/usr/bin/env") - 1]
        user = next(a for a in args if a.startswith("--username=")).split("=", 1)[1]
        database = next(a for a in args if a.startswith("--dbname=")).split("=", 1)[1]
        container = self.containers[identity]
        allowed = {
            hosted_runtime.OWNER_HBA: ("grow_perf_owner", "btmt_grow_perf"),
            hosted_runtime.PREPARATION_HBA: ("postgres", "btmt_grow_perf"),
            hosted_runtime.CANDIDATE_HBA: ("grow_perf_app", "btmt_grow_perf"),
        }
        if container["hba"] is not None and (user, database) != allowed[Path(container["hba"]).read_text()]:
            raise subprocess.CalledProcessError(2, "psql", stderr="FATAL: pg_hba.conf rejects connection")
        if stdin == ROLE_PROOF_SQL:
            return "t"
        if "pg_get_functiondef" in (stdin or ""):
            return "CREATE FUNCTION f()"
        if stdin == "SELECT 1":
            return "1"
        if stdin == "SHOW server_version_num":
            return "160004"
        return ""


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        # Unix socket paths are limited to ~100 bytes; the platform temp root is too long.
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name).resolve()
        self.bundle, self.workspace = root / "bundle", root / "work"
        self.bundle.mkdir()
        self.workspace.mkdir()
        for name, content in (("prepare.py", PREPARE), ("grow_perf_settings.py", SETTINGS)):
            (self.bundle / name).write_bytes(content)
        self.session = Session.parse(raw_manifest())
        self.docker = FakeDocker(self.session)
        self.checks = 0
        approval = {
            "version": 2,
            "identity": self.session.identity,
            "postgres_uid": 70,
            "base_uid": 1000,
            "head_uid": 1001,
            "memory": 512 * 1024**2,
            "cpus": 2,
            "tasks": 256,
            "routines": [{"signature": "public.f()", "sha256": digest(b"CREATE FUNCTION f()")}],
        }
        self.approval = approval
        for target, replacement in (
            ("benchmarks.catalogue.hosted_runtime.trusted_json", lambda path: copy.deepcopy(self.approval)),
            ("benchmarks.catalogue.hosted_runtime.schema_bytes", lambda path: path.read_bytes()),
            ("benchmarks.catalogue.hosted_runtime.restore_approved", lambda *args: {}),
            ("benchmarks.catalogue.hosted_runtime.os.chown", lambda *args: None),
            ("benchmarks.catalogue.hosted_runtime.HostedRuntime.http_ready", staticmethod(lambda path: True)),
        ):
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def check(self):
        self.checks += 1

    def runtime(self, **options):
        return hosted_runtime.HostedRuntime(
            self.session,
            INVOCATION,
            self.bundle,
            self.workspace,
            options.pop("check", self.check),
            docker=self.docker,
            namespace=lambda pid: 1 if pid == 1 else 2,
        )

    def test_round_serves_after_a_verified_handoff_and_reuses_the_prepared_side(self):
        runtime = self.runtime()
        with runtime.prepare(self.session.base, 1) as endpoint:
            self.assertEqual(endpoint.unix_socket.name, "api.sock")
        restores = sum(1 for call in self.docker.calls if call[0] == "create" and "initdb" in " ".join(call))
        with runtime.prepare(self.session.base, 2):
            pass
        self.assertEqual(restores, 1)
        self.assertEqual(sum(1 for call in self.docker.calls if "initdb" in " ".join(call)), 1)
        self.assertFalse(self.docker.containers)
        self.assertGreater(self.checks, 0)

    def test_forged_provenance_is_rejected_before_any_container_exists(self):
        self.docker.tamper["RepoDigests"] = ["ghcr.io/behindthemusictree/grow@sha256:" + "0" * 64]
        with self.assertRaisesRegex(RuntimeError, "admitted digest"):
            self.runtime()
        self.assertFalse(any(call[0] == "create" for call in self.docker.calls))

    def test_isolation_mismatch_prevents_start_and_removes_the_container(self):
        runtime = self.runtime()
        for field, value in (
            ("NetworkMode", "host"),
            ("ReadonlyRootfs", False),
            ("Privileged", True),
            ("CapAdd", ["NET_ADMIN"]),
            ("PidMode", "host"),
            ("Memory", 1),
        ):
            self.docker.tamper = {"HostConfig": {field: value}}
            before = len(self.docker.calls)
            with self.assertRaisesRegex(RuntimeError, "isolation"), runtime.prepare(self.session.base, 1):
                pass
            self.assertFalse(any(call[0] == "start" for call in self.docker.calls[before:]), field)
            self.assertFalse(self.docker.containers)
            runtime.sides.clear()

    def test_host_network_namespace_is_rejected_after_start(self):
        runtime = hosted_runtime.HostedRuntime(
            self.session,
            INVOCATION,
            self.bundle,
            self.workspace,
            self.check,
            docker=self.docker,
            namespace=lambda pid: 1,
        )
        with self.assertRaisesRegex(RuntimeError, "host network"), runtime.prepare(self.session.base, 1):
            pass
        self.assertFalse(self.docker.containers)

    def test_altered_preparation_artifact_or_approval_is_rejected(self):
        (self.bundle / "prepare.py").write_bytes(b"print('other')\n")
        with self.assertRaisesRegex(ValueError, "preparation artifact"):
            self.runtime()
        (self.bundle / "prepare.py").write_bytes(PREPARE)
        self.approval["identity"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "exact admitted session"):
            self.runtime()
        self.approval["identity"] = self.session.identity
        self.approval["memory"] = 64 * 1024**3
        with self.assertRaisesRegex(ValueError, "container memory"):
            self.runtime()

    def test_routine_definition_must_match_approval(self):
        self.approval["routines"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "routine definition"), self.runtime().prepare(self.session.base, 1):
            pass

    def test_failed_removal_blocks_further_rounds(self):
        runtime = self.runtime()
        self.docker.fail_rm = True
        with self.assertRaises(subprocess.CalledProcessError), runtime.prepare(self.session.base, 1):
            pass
        self.assertTrue(runtime.cleanup_uncertain)
        with self.assertRaises(ValueError):
            runtime.prepare(self.session.base, 2).__enter__()

    def test_close_fails_when_a_labelled_container_survives(self):
        runtime = self.runtime()
        self.docker.leak = True
        with self.assertRaisesRegex(RuntimeError, "survived"):
            runtime.close()

    def test_deadline_check_stops_execution(self):
        def expired():
            raise hosted.DeadlineExceeded("deadline")

        runtime = self.runtime()
        runtime.check = expired
        with self.assertRaises(hosted.DeadlineExceeded), runtime.prepare(self.session.base, 1):
            pass


class VerdictTest(unittest.TestCase):
    def setUp(self):
        self.session = Session.parse(raw_manifest())

    def verdict(self, **changes):
        value = hosted.verdict_for(self.session, "infrastructure_failure", None, None, "cleanup")
        value.update(changes)
        return value

    def test_valid_shapes(self):
        hosted.validate_verdict(self.verdict(), self.session)
        decision = {"status": "passed"}
        hosted.validate_verdict(
            self.verdict(status="passed", decision=decision, evidence_sha256="a" * 64, cause=None), self.session
        )

    def test_invalid_shapes_are_rejected(self):
        decision = {"status": "passed"}
        for changes in (
            {"cause": None},
            {"cause": "other"},
            {"decision": decision},
            {"status": "passed", "decision": decision, "evidence_sha256": "a" * 64},
            {"status": "passed", "decision": {"status": "failed"}, "evidence_sha256": "a" * 64, "cause": None},
            {"status": "passed", "decision": decision, "evidence_sha256": None, "cause": None},
            {"status": "unknown"},
            {"identity": "0" * 64},
            {"version": 2},
        ):
            with self.assertRaises(ValueError, msg=str(changes)):
                hosted.validate_verdict(self.verdict(**changes), self.session)
        with self.assertRaises(ValueError):
            hosted.validate_verdict({**self.verdict(), "extra": 1}, self.session)

    def test_verify_rejects_altered_evidence_and_accepts_the_original(self):
        names = ["scenario_" + str(i) for i in range(10)]
        policy = {
            "version": 1,
            "algorithm": "grow-paired-median-v1",
            "ratio": 1.3,
            "floor_ms": 5,
            "min_drift_scenarios": 10,
            "min_split_rounds": 2,
            "slo_ms": dict.fromkeys(names, 1000),
        }
        inventory = {
            "version": 1,
            "policy_sha256": digest(canonical_bytes(policy)),
            "scenarios": [{"name": name, "requests": 2, "definition_sha256": "a" * 64} for name in names],
        }
        session = Session.parse(
            raw_manifest(scenario_sha256=digest(canonical_bytes(inventory)), policy_sha256=inventory["policy_sha256"])
        )
        evidence = {
            "version": 1,
            "manifest": session.as_dict(),
            "invocation": INVOCATION,
            "scenario_plan": inventory,
            "comparison_policy": policy,
            "scenarios": names,
            "measurements": [
                {
                    "side": side,
                    "round": number,
                    "scenario": name,
                    "sha": getattr(session, side).sha,
                    "image": getattr(session, side).image,
                    "requests": 2,
                    "errors": 0,
                    "correct": True,
                    "latency_ms": [100.0, 100.0],
                }
                for side, number in session.schedule()
                for name in names
            ],
        }
        evidence["decision"] = hosted.decide(evidence, session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def publish(value):
                content = canonical_bytes(value)
                (root / "evidence.json").write_bytes(content)
                verdict = hosted.verdict_for(session, "passed", evidence["decision"], digest(content), None)
                (root / "verdict.json").write_bytes(canonical_bytes(verdict))

            publish(evidence)
            self.assertEqual(hosted.verify(session, root)["status"], "passed")
            forged = copy.deepcopy(evidence)
            forged["measurements"][0]["latency_ms"] = [1.0, 1.0]
            publish(forged)  # digest matches, but the embedded decision no longer does
            with self.assertRaises(ValueError):
                hosted.verify(session, root)
            missing = copy.deepcopy(evidence)
            del missing["measurements"][-1]
            publish(missing)
            with self.assertRaises(ValueError):
                hosted.verify(session, root)
            publish(evidence)
            (root / "evidence.json").write_bytes((root / "evidence.json").read_bytes() + b" ")
            with self.assertRaises(ValueError):
                hosted.verify(session, root)


if __name__ == "__main__":
    unittest.main()
