"""Interpret Grow's pinned paired-round policy using trusted observations.

The versioned algorithm follows Grow perf.compare: paired median ratios and
absolute floors, with within-side drift removed for repeated plan splits.
Policy parameters and full-scale SLOs belong to the approved Grow artifact.
"""

import hashlib
import math
import statistics
from dataclasses import dataclass
from itertools import pairwise

from .manifest import Session, exact_keys, positive_integer
from .measurement_evidence import validate_measurements
from .scenario_plan import ScenarioPlan, canonical_bytes


def positive_number(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"invalid {name}")
    return value


@dataclass(frozen=True)
class Policy:
    ratio: float
    floor_ms: float
    min_drift_scenarios: int
    min_split_rounds: int
    slo_ms: dict[str, float]

    @classmethod
    def parse(cls, raw: object, plan: ScenarioPlan) -> Policy:
        value = exact_keys(
            raw, {"version", "algorithm", "ratio", "floor_ms", "min_drift_scenarios", "min_split_rounds", "slo_ms"}
        )
        if type(value["version"]) is not int or value["version"] != 1 or value["algorithm"] != "grow-paired-median-v1":
            raise ValueError("unsupported performance comparison policy")
        if hashlib.sha256(canonical_bytes(value)).hexdigest() != plan.policy_sha256:
            raise ValueError("comparison policy differs from the admitted scenario inventory")
        ratio = positive_number(value["ratio"], "regression ratio")
        if ratio <= 1:
            raise ValueError("regression ratio must exceed one")
        slo = exact_keys(value["slo_ms"], set(plan.names))
        return cls(
            ratio,
            positive_number(value["floor_ms"], "absolute regression floor"),
            positive_integer(value["min_drift_scenarios"], "drift scenario minimum", 3, 128),
            positive_integer(value["min_split_rounds"], "plan split minimum", 2, 6),
            {name: positive_number(slo[name], "scenario SLO") for name in plan.names},
        )

    def unstable(self, values: list[float]) -> bool:
        values = sorted(values)
        lowest, highest = (
            (1, len(values) - 1)
            if len(values) < 2 * self.min_split_rounds
            else (self.min_split_rounds, len(values) - self.min_split_rounds)
        )
        return any(
            high > low * self.ratio and high - low > self.floor_ms
            for size, (low, high) in enumerate(pairwise(values), start=1)
            if lowest <= size <= highest
        )


def decide(evidence: dict, session: Session) -> dict:
    validate_measurements(evidence, session)
    plan = ScenarioPlan.parse(evidence["scenario_plan"], session.scenario_sha256)
    policy = Policy.parse(evidence.get("comparison_policy"), plan)
    rows = evidence["measurements"]
    timings = {
        side: {
            name: [row["latency_ms"] for row in rows if row["side"] == side and row["scenario"] == name]
            for name in plan.names
        }
        for side in ("base", "head")
    }
    medians = {
        side: {name: [statistics.median(samples) for samples in rounds] for name, rounds in scenarios.items()}
        for side, scenarios in timings.items()
    }
    drift = {side: [1.0] * session.rounds for side in timings}
    if len(plan.names) >= policy.min_drift_scenarios:
        for side in timings:
            usual = {name: statistics.median(values) for name, values in medians[side].items()}
            drift[side] = [
                statistics.median(medians[side][name][number] / usual[name] for name in plan.names)
                for number in range(session.rounds)
            ]
    results = []
    for name in plan.names:
        base, head = medians["base"][name], medians["head"][name]
        ratio = statistics.median(after / before for before, after in zip(base, head, strict=True))
        summary = {}
        unstable = []
        for side in timings:
            samples = sorted(sample for values in timings[side][name] for sample in values)
            summary[side] = {
                "p50_ms": statistics.median(samples),
                "p95_ms": samples[math.ceil(len(samples) * 0.95) - 1],
                "round_p50_ms": medians[side][name],
            }
            settled = [value / factor for value, factor in zip(medians[side][name], drift[side], strict=True)]
            if policy.unstable(settled):
                unstable.append(side)
        reasons = ["unstable_" + side for side in unstable]
        if summary["head"]["p50_ms"] > policy.slo_ms[name]:
            reasons.append("slo_breach")
        if ratio > policy.ratio and summary["base"]["p50_ms"] * (ratio - 1) > policy.floor_ms:
            reasons.append("regression")
        results.append(dict(scenario=name, ratio=ratio, reasons=reasons, **summary))
    reasons = [reason for result in results for reason in result["reasons"]]
    status = (
        "inconclusive"
        if any(reason.startswith("unstable_") for reason in reasons)
        else "failed"
        if reasons
        else "passed"
    )
    return {"status": status, "algorithm": "grow-paired-median-v1", "drift": drift, "scenarios": results}
