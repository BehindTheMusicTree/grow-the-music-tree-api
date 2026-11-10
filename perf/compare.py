"""Judge perf results: absolute SLOs on the head, and regressions against a base measured on the same runner.

Usage: python -m perf.compare --head head-*.json [--base base-*.json] [--summary out.md] [--accept-regressions]

Every input is a file named <side>-<round>.json written by perf/conftest.py (PERF_RESULTS), one per round. Base and
head run back to back in strict alternation, so round i of one is paired with round i of the other: `slower` is judged
on the median of the head/base ratios of the pairs, which cancels the runner's drift.

A side is unstable when its round medians split into two groups (a gap above RATIO and FLOOR_MS between consecutive
sorted values): its pooled median would sit between two plans that no request actually took. Runner drift moves every
scenario of a round together, so it is estimated within the side (median over scenarios of round p50 / usual p50) and
removed before that test; what is left is a scenario diverging from the others.
With four rounds or more, each group must hold at least MIN_SPLIT_ROUNDS rounds: one odd round is noise (it leaves the
pooled median on the majority plan), while fewer rounds cannot tell, so the gap stays suspect and the runner measures more.
Limit: a shift of most scenarios in the same round of one side reads as drift; only `slower` (paired ratios) can still
catch it, and only when about half the rounds are affected. A scenario missing from some rounds is judged raw.
Exit 0 when clean, 1 on an SLO breach, a regression or an unstable side.
"""

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

# A slowdown counts only when it exceeds both the ratio and the absolute floor, so ~10 ms endpoints don't flag on a
# few ms of jitter. Starting values, to be confirmed with base == head runs on GitHub-hosted runners: the spread seen
# on a laptop came from stale planner statistics after the bulk merges (fixed by their ANALYZE) plus load spikes, so
# these constants are not meant to be calibrated locally.
RATIO = 1.3
FLOOR_MS = 5.0
# Drift is the median over scenarios of a round's p50 relative to the usual one. With few scenarios, one plan flip
# would move that median, so below this count the rounds are judged raw.
MIN_DRIFT_SCENARIOS = 10
# A real plan flip repeats, and a lone round on one side of a gap does not move the pooled median. With enough rounds,
# a gap counts only when each group holds at least this many; with fewer, a gap stays suspect so the verdict escalates.
MIN_SPLIT_ROUNDS = 2

OK, SLOWER, SLO_BREACH, MORE_QUERIES, NEW, REMOVED = "ok", "slower", "over SLO", "more queries", "new", "removed"
UNSTABLE_BASE, UNSTABLE_HEAD = "unstable base", "unstable head"


@dataclass(frozen=True)
class Side:
    p50: float
    slo_ms: float | None
    queries: int | None
    rounds: tuple[float, ...] = ()
    drift: tuple[float, ...] = ()

    @property
    def settled(self) -> tuple[float, ...]:
        """Round medians with the runner's drift of that round removed."""
        if not self.drift:
            return self.rounds
        return tuple(value / factor for value, factor in zip(self.rounds, self.drift, strict=True))

    @property
    def unstable(self) -> bool:
        """Two groups of rounds further apart than a slowdown would need: the side measured two plans, not one."""
        values = sorted(self.settled)
        if len(values) < 2 * MIN_SPLIT_ROUNDS:
            lowest, highest = 1, len(values) - 1
        else:
            lowest, highest = MIN_SPLIT_ROUNDS, len(values) - MIN_SPLIT_ROUNDS
        return any(
            high > low * RATIO and high - low > FLOOR_MS
            for size, (low, high) in enumerate(pairwise(values), start=1)
            if lowest <= size <= highest
        )


@dataclass(frozen=True)
class Row:
    scenario: str
    base: Side | None
    head: Side | None
    statuses: tuple[str, ...]
    ratio: float | None = None

    @property
    def failing(self) -> bool:
        return any(
            status in (SLOWER, SLO_BREACH, MORE_QUERIES, UNSTABLE_BASE, UNSTABLE_HEAD) for status in self.statuses
        )


def _round_number(path: Path) -> int:
    match = re.fullmatch(r"(?:base|head)-(\d+)\.json", path.name)
    if match is None:
        raise ValueError(f"{path}: expected a name like head-1.json, the round number pairs base with head")
    return int(match.group(1))


def _drift(rounds: dict[str, list[float]]) -> tuple[float, ...]:
    """Per round, how much slower the runner was for every scenario at once, within one side."""
    count = max(len(values) for values in rounds.values())
    full = [values for values in rounds.values() if len(values) == count]
    if len(full) < MIN_DRIFT_SCENARIOS or count < 2:
        return ()
    usual = [statistics.median(values) for values in full]
    return tuple(
        statistics.median(values[i] / ref for values, ref in zip(full, usual, strict=True)) for i in range(count)
    )


def load(paths: list[Path]) -> dict[str, Side]:
    if not paths:
        raise ValueError("no result files given")
    paths = sorted(paths, key=_round_number)
    timings: dict[str, list[float]] = {}
    rounds: dict[str, list[float]] = {}
    meta: dict[str, tuple[float | None, int | None]] = {}
    for path in paths:
        payload = json.loads(path.read_text())
        if payload.get("version") != 1 or not payload.get("scenarios"):
            raise ValueError(f"{path}: not a perf result file, or it holds no scenario")
        for scenario, result in payload["scenarios"].items():
            timings.setdefault(scenario, []).extend(result["timings_ms"])
            rounds.setdefault(scenario, []).append(statistics.median(result["timings_ms"]))
            queries = result["queries"]
            previous = meta.get(scenario)
            # A count can differ between runs only through caching; the worst run is the one that matters.
            if previous is not None and previous[1] is not None and queries is not None:
                queries = max(queries, previous[1])
            meta[scenario] = (result["slo_ms"], queries)
    drift = _drift(rounds)
    return {
        name: Side(
            statistics.median(values),
            *meta[name],
            rounds=tuple(rounds[name]),
            drift=drift if len(rounds[name]) == len(drift) else (),
        )
        for name, values in timings.items()
    }


def paired_ratio(before: Side, after: Side) -> float:
    """Median of head/base over rounds measured back to back, so drift common to both cancels."""
    if before.rounds and after.rounds:
        if len(before.rounds) != len(after.rounds):
            raise ValueError("base and head were measured over a different number of rounds")
        return statistics.median(a / b for a, b in zip(after.rounds, before.rounds, strict=True))
    return after.p50 / before.p50


def compare(base: dict[str, Side] | None, head: dict[str, Side], *, accept_regressions: bool = False) -> list[Row]:
    rows = []
    for scenario in sorted(set(head) | set(base or {})):
        before, after = (base or {}).get(scenario), head.get(scenario)
        statuses: list[str] = []
        ratio = paired_ratio(before, after) if before is not None and after is not None else None
        if after is None:
            statuses.append(REMOVED)
        else:
            if (after.slo_ms is not None and after.p50 > after.slo_ms) or (
                before is not None and before.slo_ms is not None and after.slo_ms is None
            ):
                statuses.append(SLO_BREACH)
            if after.unstable:
                statuses.append(UNSTABLE_HEAD)
            if base is not None and before is None:
                statuses.append(NEW)
            elif before is not None and before.unstable and not accept_regressions:
                # A slowdown against a base median that no request took means nothing either way.
                statuses.append(UNSTABLE_BASE)
            elif before is not None and not accept_regressions:
                if ratio is not None and ratio > RATIO and before.p50 * (ratio - 1) > FLOOR_MS:
                    statuses.append(SLOWER)
                if before.queries is not None and after.queries is not None and after.queries > before.queries:
                    statuses.append(MORE_QUERIES)
        rows.append(Row(scenario, before, after, tuple(statuses) or (OK,), ratio))
    return rows


def _ms(side: Side | None) -> str:
    return "-" if side is None else f"{side.p50:.1f}"


def _rounds(side: Side | None) -> str:
    return "-" if side is None or not side.rounds else " / ".join(f"{p50:.0f}" for p50 in side.rounds)


def _queries(row: Row) -> str:
    before = row.base.queries if row.base else None
    after = row.head.queries if row.head else None
    if after is None:
        return "-"
    return str(after) if before in (None, after) else f"{before} → {after}"


def _drift_line(rows: list[Row]) -> str | None:
    parts = []
    for name, sides in (("base", [row.base for row in rows]), ("head", [row.head for row in rows])):
        drift = next((side.drift for side in sides if side and side.drift), ())
        if drift:
            parts.append(f"{name} " + " / ".join(f"{factor:.2f}" for factor in drift))
    return f"Runner drift per round (removed before the unstable test): {'; '.join(parts)}." if parts else None


def render(rows: list[Row], *, with_base: bool, accept_regressions: bool) -> str:
    failing = [row for row in rows if row.failing]
    title = "❌ Perf regression" if failing else "✅ Perf"
    lines = [f"## {title}", ""]
    if with_base:
        lines.append(
            f"p50 of all runs, base and head interleaved on the same runner. A scenario is slower when the median of "
            f"the head/base ratios of the paired rounds exceeds {RATIO}x **and** adds {FLOOR_MS:.0f} ms. A side is "
            f"unstable when its drift-corrected round p50s split into two groups that far apart, each of at least "
            f"{MIN_SPLIT_ROUNDS} rounds once there are {2 * MIN_SPLIT_ROUNDS} (an unstable head "
            f"fails even with the label)."
        )
        drift_line = _drift_line(rows)
        if drift_line:
            lines += ["", drift_line]
        if accept_regressions:
            lines.append("")
            lines.append("⚠️ `perf-regression-accepted` label: slowdowns and query increases are reported, not failed.")
        lines += [
            "",
            "| Scenario | Base p50 (ms) | Head p50 (ms) | Δ | Base rounds | Head rounds | Queries | SLO (ms) | Status |",
            "|---|--:|--:|--:|--:|--:|--:|--:|---|",
        ]
    else:
        lines += ["", "| Scenario | p50 (ms) | Rounds | Queries | SLO (ms) | Status |", "|---|--:|--:|--:|--:|---|"]
    for row in rows:
        status = ", ".join(row.statuses)
        status = f"**{status}**" if row.failing else status
        slo = f"{row.head.slo_ms:.0f}" if row.head and row.head.slo_ms is not None else "pending calibration"
        if with_base:
            delta = f"{(row.ratio - 1) * 100:+.0f}%" if row.ratio is not None else "-"
            cells = [row.scenario, _ms(row.base), _ms(row.head), delta, _rounds(row.base), _rounds(row.head)]
            cells += [_queries(row), slo, status]
        else:
            cells = [row.scenario, _ms(row.head), _rounds(row.head), _queries(row), slo, status]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--head", type=Path, nargs="+", required=True)
    parser.add_argument("--base", type=Path, nargs="+")
    parser.add_argument("--summary", type=Path, help="append the Markdown report to this file")
    parser.add_argument("--accept-regressions", action="store_true")
    args = parser.parse_args(argv)

    base = load(args.base) if args.base else None
    rows = compare(base, load(args.head), accept_regressions=args.accept_regressions)
    report = render(rows, with_base=base is not None, accept_regressions=args.accept_regressions)
    sys.stdout.write(report)
    if args.summary:
        with args.summary.open("a") as file:
            file.write(report)
    return 1 if any(row.failing for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
