"""Durable session outcomes outside disposable benchmark storage.

A running or interrupted record is never a passing report. Only the external
driver may finalize success, after the coordinator acknowledges cleanup.
"""

import json
import os
import uuid
from pathlib import Path

from .manifest import Session, exact_keys, matching, sha256_file, trusted_json
from .measurement_evidence import MAX_EVIDENCE_BYTES, validate_measurements
from .performance_decision import decide
from .private_files import private_path, sync_directory


class Report:
    def __init__(self, root: Path, session: Session):
        private_path(root, directory=True)
        self.directory = root / f"{session.identity}-{uuid.uuid4().hex}"
        self.directory.mkdir(mode=0o700)
        sync_directory(root)
        self.value = {
            "version": 1,
            "identity": session.identity,
            "manifest": session.as_dict(),
            "status": "running",
            "cleanup_acknowledged": False,
            "cause": None,
        }
        self.write()

    def verify_execution(self, receipt: Path, invocation: str) -> str:
        matching(invocation, r"[0-9a-f]{32}", "controller invocation")
        value = exact_keys(
            trusted_json(receipt), {"version", "identity", "invocation", "status", "evidence", "evidence_sha256"}
        )
        if (
            type(value["version"]) is not int
            or value["version"] != 1
            or value["identity"] != self.value["identity"]
            or value["invocation"] != invocation
            or value["status"] != "passed"
            or not isinstance(value["evidence"], str)
        ):
            raise ValueError("execution receipt does not prove this session and controller invocation passed")
        evidence = Path(value["evidence"])
        trusted_json(evidence, maximum_bytes=MAX_EVIDENCE_BYTES)
        # Retain the exact evidence before publishing a passing outcome. The
        # controller's original storage may be reclaimed after this session.
        retained = self.directory / "evidence.json"
        with retained.open("xb") as output:
            retained.chmod(0o600)
            output.write(evidence.read_bytes())
            output.flush()
            os.fsync(output.fileno())
        evidence_value = trusted_json(retained, maximum_bytes=MAX_EVIDENCE_BYTES)
        if (
            type(evidence_value.get("version")) is not int
            or evidence_value["version"] != 1
            or evidence_value.get("invocation") != invocation
            or Session.parse(evidence_value.get("manifest")).as_dict() != self.value["manifest"]
        ):
            raise ValueError("execution evidence differs from the requested manifest or controller invocation")
        validate_measurements(evidence_value, Session.parse(self.value["manifest"]))
        decision = decide(evidence_value, Session.parse(self.value["manifest"]))
        if decision["status"] != "passed" or evidence_value.get("decision") != decision:
            raise ValueError("execution evidence does not establish a passing performance decision")
        digest = sha256_file(retained)
        if digest != value["evidence_sha256"]:
            raise ValueError("execution evidence digest differs")
        self.value["evidence_sha256"] = digest
        self.value["evidence"] = str(retained)
        self.value["invocation"] = invocation
        return digest

    def write(self, value: dict | None = None) -> None:
        pending = self.directory / "report.pending.json"
        try:
            with pending.open("x") as output:
                pending.chmod(0o600)
                json.dump(self.value if value is None else value, output, sort_keys=True, separators=(",", ":"))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            pending.replace(self.directory / "report.json")
            sync_directory(self.directory)
        finally:
            pending.unlink(missing_ok=True)

    def finish(self, *, passed: bool, cleanup_acknowledged: bool, cause: str | None = None) -> None:
        if self.value["status"] != "running":
            raise RuntimeError("session report is already final")
        if passed and (not cleanup_acknowledged or cause is not None or "evidence_sha256" not in self.value):
            raise ValueError("passing report requires acknowledged cleanup and no failure")
        value = dict(
            self.value,
            status="passed" if passed else "interrupted",
            cleanup_acknowledged=cleanup_acknowledged,
            cause=cause,
        )
        self.write(value)
        self.value = value
