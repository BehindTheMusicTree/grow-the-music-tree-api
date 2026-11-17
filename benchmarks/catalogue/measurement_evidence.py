"""Validate complete trusted observations before accepting execution evidence.

The controller supplies observations, never candidate-authored summaries. Grow
owns scenario semantics and the performance decision; this validates coverage
and rejects missing or malformed observations at the report boundary.
"""

import math

from .manifest import Session, exact_keys, positive_integer
from .scenario_plan import ScenarioPlan

MAX_SAMPLES = 100000
MAX_EVIDENCE_BYTES = 16 * 1024**2


def validate_measurements(value: dict, session: Session) -> None:
    plan = ScenarioPlan.parse(value.get("scenario_plan"), session.scenario_sha256)
    if sum(plan.requests) * session.rounds * 2 > MAX_SAMPLES:
        raise ValueError("session exceeds the trusted measurement sample budget")
    scenarios = list(plan.names)
    if value.get("scenarios") != scenarios:
        raise ValueError("execution scenarios differ from the approved inventory")
    measurements = value.get("measurements")
    if not isinstance(measurements, list) or len(measurements) != len(scenarios) * session.rounds * 2:
        raise ValueError("execution measurements do not cover every scenario and round")
    expected = [(side, number, scenario) for side, number in session.schedule() for scenario in scenarios]
    for raw, (side, number, scenario) in zip(measurements, expected, strict=True):
        item = exact_keys(
            raw, {"side", "round", "scenario", "sha", "image", "requests", "errors", "correct", "latency_ms"}
        )
        candidate = getattr(session, side)
        if (
            item["side"] != side
            or type(item["round"]) is not int
            or item["round"] != number
            or item["scenario"] != scenario
            or item["sha"] != candidate.sha
            or item["image"] != candidate.image
        ):
            raise ValueError("measurement differs from the scheduled candidate execution")
        count = positive_integer(item["requests"], "measured request count", 1, 10000)
        if count != plan.requests[scenarios.index(scenario)]:
            raise ValueError("measurement request count differs from the approved inventory")
        if type(item["errors"]) is not int or item["errors"] != 0 or item["correct"] is not True:
            raise ValueError("execution includes request errors or incorrect results")
        samples = item["latency_ms"]
        if not isinstance(samples, list) or len(samples) != count:
            raise ValueError("latency sample count differs from requests")
        if any(type(sample) not in (int, float) or not math.isfinite(sample) or sample <= 0 for sample in samples):
            raise ValueError("latency samples must be finite positive numbers")
