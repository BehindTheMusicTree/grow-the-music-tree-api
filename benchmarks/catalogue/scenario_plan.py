"""Immutable Grow scenario inventory bound to the admitted session.

Grow supplies scenario definitions and the comparison policy as immutable
artifacts. This inventory pins their hashes and the required sample counts;
it does not interpret application queries or decide performance outcomes.
"""

import hashlib
import json
from dataclasses import dataclass

from .manifest import exact_keys, matching, positive_integer


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


@dataclass(frozen=True)
class ScenarioPlan:
    names: tuple[str, ...]
    requests: tuple[int, ...]
    policy_sha256: str

    @classmethod
    def parse(cls, raw: object, expected_sha256: str) -> ScenarioPlan:
        value = exact_keys(raw, {"version", "scenarios", "policy_sha256"})
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("unsupported scenario inventory version")
        policy = matching(value["policy_sha256"], r"[0-9a-f]{64}", "comparison policy digest")
        scenarios = value["scenarios"]
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 128:
            raise ValueError("scenario inventory requires 1 to 128 scenarios")
        names, counts = [], []
        for raw_item in scenarios:
            item = exact_keys(raw_item, {"name", "requests", "definition_sha256"})
            names.append(matching(item["name"], r"[a-z][a-z0-9_-]{0,63}", "scenario name"))
            counts.append(positive_integer(item["requests"], "scenario request count", 1, 10000))
            matching(item["definition_sha256"], r"[0-9a-f]{64}", "scenario definition digest")
        if len(set(names)) != len(names):
            raise ValueError("duplicate scenario inventory entry")
        if hashlib.sha256(canonical_bytes(value)).hexdigest() != expected_sha256:
            raise ValueError("scenario inventory differs from the admitted session")
        return cls(tuple(names), tuple(counts), policy)
