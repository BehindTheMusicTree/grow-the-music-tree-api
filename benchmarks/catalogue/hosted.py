"""Hosted-runner entry points: `run` produces evidence and a verdict, `verify` re-derives it.

`run` needs root (Docker, private storage). `verify` runs unprivileged in the
report job and trusts nothing in the downloaded results: it recomputes the
decision and the evidence digest from the admitted manifest.
"""

import argparse
import hashlib
import json
import os
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .controller import execute, write_private
from .hosted_runtime import HostedRuntime
from .manifest import HostedSession, Session, _unique_pairs, exact_keys, matching, trusted_json
from .measurement_evidence import MAX_EVIDENCE_BYTES
from .performance_decision import decide
from .private_files import private_path, sync_directory
from .scenario_plan import ScenarioPlan, canonical_bytes

STATUSES = {"passed", "failed", "inconclusive", "infrastructure_failure"}
CAUSES = {"input", "preparation", "measurement", "cleanup", "deadline"}
VERDICT_KEYS = {"version", "identity", "status", "decision", "evidence_sha256", "cause"}


class DeadlineExceeded(RuntimeError):
    pass


def hosted_session(path: Path) -> HostedSession:
    session = Session.parse(trusted_json(path))
    if not isinstance(session, HostedSession):
        raise ValueError("a hosted session manifest (version 2) is required")
    return session


def load_json(path: Path, maximum: int) -> dict:
    """Parse untrusted results: bounded, regular file, no duplicate keys."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if info.st_size > maximum or not os.path.isfile(path):
            raise ValueError("results file is too large or not regular")
        content = source.read(maximum + 1)
    value = json.loads(content, object_pairs_hook=_unique_pairs)
    if not isinstance(value, dict):
        raise ValueError("results file must hold an object")
    return value


def validate_verdict(raw: object, session: Session) -> dict:
    value = exact_keys(raw, VERDICT_KEYS)
    if type(value["version"]) is not int or value["version"] != 1 or value["identity"] != session.identity:
        raise ValueError("verdict does not belong to the admitted session")
    if value["status"] not in STATUSES:
        raise ValueError("unknown verdict status")
    if value["status"] == "infrastructure_failure":
        if value["decision"] is not None or value["evidence_sha256"] is not None or value["cause"] not in CAUSES:
            raise ValueError("an infrastructure failure carries a cause and no evidence")
        return value
    matching(value["evidence_sha256"], r"[0-9a-f]{64}", "evidence digest")
    if value["cause"] is not None:
        raise ValueError("only an infrastructure failure carries a cause")
    if not isinstance(value["decision"], dict) or value["decision"].get("status") != value["status"]:
        raise ValueError("verdict status differs from its decision")
    return value


def verify(session: Session, directory: Path) -> dict:
    """Recompute everything a report may rely on; raise on any inconsistency."""
    verdict = validate_verdict(load_json(directory / "verdict.json", 4 * 1024**2), session)
    if verdict["status"] == "infrastructure_failure":
        return verdict
    evidence_path = directory / "evidence.json"
    if not stat.S_ISREG(evidence_path.lstat().st_mode):
        raise ValueError("evidence must be a regular file")
    content = evidence_path.read_bytes() if evidence_path.stat().st_size <= MAX_EVIDENCE_BYTES else None
    if content is None or hashlib.sha256(content).hexdigest() != verdict["evidence_sha256"]:
        raise ValueError("evidence digest differs from the verdict")
    evidence = load_json(evidence_path, MAX_EVIDENCE_BYTES)
    if canonical_bytes(evidence) != content or evidence.get("manifest") != session.as_dict():
        raise ValueError("evidence is not canonical or belongs to another session")
    plan = ScenarioPlan.parse(evidence.get("scenario_plan"), session.scenario_sha256)
    if plan.policy_sha256 != session.policy_sha256:
        raise ValueError("comparison policy differs from the admitted session")
    if hashlib.sha256(canonical_bytes(evidence.get("comparison_policy"))).hexdigest() != plan.policy_sha256:
        raise ValueError("comparison policy digest mismatch")
    decision = decide(evidence, session)
    if decision != evidence.get("decision") or decision != verdict["decision"]:
        raise ValueError("recomputed decision differs from the published one")
    return verdict


class Phase:
    """Attributes a failure to preparation or measurement for the verdict cause."""

    def __init__(self, runtime: HostedRuntime):
        self.runtime, self.name = runtime, "preparation"

    @contextmanager
    def prepare(self, candidate, number):
        self.name = "preparation"
        with self.runtime.prepare(candidate, number) as endpoint:
            self.name = "measurement"
            yield endpoint


def verdict_for(session: Session, status: str, decision, digest, cause) -> dict:
    return {
        "version": 1,
        "identity": session.identity,
        "status": status,
        "decision": decision,
        "evidence_sha256": digest,
        "cause": cause,
    }


def run(session: HostedSession, invocation: str, bundle: Path, artifacts: Path, workspace: Path, results: Path) -> dict:
    if os.geteuid() != 0:
        raise RuntimeError("hosted runner must run as root")
    for path in (results, workspace, bundle, artifacts):
        private_path(path, directory=True)
    directory = results / matching(invocation, r"[0-9a-f]{32}", "controller invocation")
    directory.mkdir(mode=0o700)
    sync_directory(results)

    def check() -> None:
        if time.time() >= session.deadline_timestamp:
            raise DeadlineExceeded("benchmark deadline reached")

    cause, evidence, runtime, phase = "input", None, None, None
    try:
        check()
        runtime = HostedRuntime(session, invocation, bundle, workspace, check)
        phase = Phase(runtime)
        cause = "preparation"
        evidence = execute(session, invocation, artifacts, phase, check)
    except BaseException as error:
        if isinstance(error, DeadlineExceeded):
            cause = "deadline"
        elif phase is not None:
            cause = phase.name
    cleaned = True
    if runtime is not None:
        try:
            runtime.close()
        except BaseException:
            cleaned = False
    if evidence is not None and cleaned:
        try:
            content = canonical_bytes(evidence)
            if len(content) > MAX_EVIDENCE_BYTES:
                raise ValueError("execution evidence exceeds the trusted reader limit")
            write_private(directory / "evidence.json", content)
            status = evidence["decision"]["status"]
            verdict = verdict_for(session, status, evidence["decision"], hashlib.sha256(content).hexdigest(), None)
        except BaseException:
            verdict = verdict_for(session, "infrastructure_failure", None, None, "measurement")
    else:
        # A cleanup failure overrides any measurement outcome.
        verdict = verdict_for(session, "infrastructure_failure", None, None, "cleanup" if not cleaned else cause)
    validate_verdict(verdict, session)
    write_private(directory / "verdict.json", canonical_bytes(verdict))
    return verdict


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run")
    for name in ("manifest", "bundle", "artifacts", "workspace", "results"):
        runner.add_argument("--" + name, type=Path, required=True)
    checker = commands.add_parser("verify")
    checker.add_argument("--manifest", type=Path, required=True)
    checker.add_argument("--results", type=Path, required=True)
    arguments = parser.parse_args(argv)
    session = hosted_session(arguments.manifest)
    if arguments.command == "run":
        verdict = run(
            session, uuid.uuid4().hex, arguments.bundle, arguments.artifacts, arguments.workspace, arguments.results
        )
    else:
        verdict = verify(session, arguments.results)
    print(json.dumps({"status": verdict["status"], "cause": verdict["cause"]}))
    return 0 if verdict["status"] in {"passed"} else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
