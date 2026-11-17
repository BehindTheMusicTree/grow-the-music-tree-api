"""Trusted schedule and receipt producer; candidates only serve HTTP responses.

The runtime adapter owns isolated preparation, migrations, derived-data rebuilds
and candidate lifetime. A side may be prepared once and reused read-only across
rounds, as long as every prepare call yields a freshly started endpoint, the
source archive is never exposed, and all resources stay inside the runtime. This module does not install a runtime
or approve production inputs. Its caller must provide independent health and deadline enforcement
around the whole run.
"""

import hashlib
import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .manifest import Candidate, Session, matching, trusted_json
from .measurement_evidence import MAX_EVIDENCE_BYTES, MAX_SAMPLES
from .performance_decision import Policy, decide
from .private_files import private_path, sync_directory
from .scenario_execution import HTTPScenario
from .scenario_plan import ScenarioPlan, canonical_bytes


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    unix_socket: Path | None = None


class Runtime(Protocol):
    def prepare(self, candidate: Candidate, number: int) -> AbstractContextManager[Endpoint]: ...


class BenchmarkRejected(RuntimeError):
    pass


def execute(
    session: Session,
    invocation: str,
    artifacts: Path,
    runtime: Runtime,
    check: Callable[[], None],
) -> dict:
    """Interpret pinned artifacts, then independently observe every HTTP read.

    Runtime preparation is trusted infrastructure, not a candidate hook. It
    returns an endpoint, never measurement/correctness/performance summaries.
    All definitions are verified before preparing even the first candidate.
    """
    matching(invocation, r"[0-9a-f]{32}", "controller invocation")
    private_path(artifacts, directory=True)
    inventory = trusted_json(artifacts / "inventory.json")
    plan = ScenarioPlan.parse(inventory, session.scenario_sha256)
    if sum(plan.requests) * session.rounds * 2 > MAX_SAMPLES:
        raise ValueError("session exceeds the trusted measurement sample budget")
    policy = trusted_json(artifacts / "policy.json")
    Policy.parse(policy, plan)
    definitions = [
        HTTPScenario.load(artifacts / (item["name"] + ".json"), item["definition_sha256"])
        for item in inventory["scenarios"]
    ]
    evidence = {
        "version": 1,
        "manifest": session.as_dict(),
        "invocation": invocation,
        "scenario_plan": inventory,
        "comparison_policy": policy,
        "scenarios": list(plan.names),
        "measurements": [],
    }
    for side, number in session.schedule():
        check()
        candidate = getattr(session, side)
        with runtime.prepare(candidate, number) as endpoint:
            check()
            for name, count, definition in zip(plan.names, plan.requests, definitions, strict=True):
                samples = definition.measure(
                    endpoint.host, endpoint.port, count, check, unix_socket=endpoint.unix_socket
                )
                evidence["measurements"].append(
                    {
                        "side": side,
                        "round": number,
                        "scenario": name,
                        "sha": candidate.sha,
                        "image": candidate.image,
                        "requests": count,
                        "errors": 0,
                        "correct": True,
                        "latency_ms": samples,
                    }
                )
        # A failed runtime exit/cleanup must prevent evidence publication.
        check()
    evidence["decision"] = decide(evidence, session)
    return evidence


def write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    sync_directory(path.parent)


def run(
    session: Session,
    invocation: str,
    artifacts: Path,
    runtime: Runtime,
    check: Callable[[], None],
    results: Path,
) -> Path:
    """Publish retained evidence, then a receipt only for a passing decision.

    The external driver still requires coordinator cleanup acknowledgement.
    results must be durable storage outside the disposable runtime and must
    never be mounted into any candidate container.
    """
    if os.geteuid() != 0:
        raise RuntimeError("controller must run as root")
    private_path(results, directory=True)
    matching(invocation, r"[0-9a-f]{32}", "controller invocation")
    directory = results / invocation
    directory.mkdir(mode=0o700)
    sync_directory(results)
    evidence = execute(session, invocation, artifacts, runtime, check)
    check()
    content = canonical_bytes(evidence)
    if len(content) > MAX_EVIDENCE_BYTES:
        raise ValueError("execution evidence exceeds the trusted reader limit")
    path = directory / "evidence.json"
    write_private(path, content)
    if evidence["decision"]["status"] != "passed":
        raise BenchmarkRejected("benchmark " + evidence["decision"]["status"])
    check()
    receipt = {
        "version": 1,
        "identity": session.identity,
        "invocation": invocation,
        "status": "passed",
        "evidence": str(path),
        "evidence_sha256": hashlib.sha256(content).hexdigest(),
    }
    result = directory / "receipt.json"
    write_private(result, canonical_bytes(receipt))
    return result
