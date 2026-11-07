"""Judge perf results: absolute SLOs on the head, and regressions against a base measured on the same runner.

Usage: python -m perf.compare --head head-*.json [--base base-*.json] [--summary out.md] [--accept-regressions]

Every input is a file written by perf/conftest.py (PERF_RESULTS), one per round. Timings of all rounds of one side are
pooled, so interleaved base/head runs cancel out the runner's drift. A side whose round medians disagree is unstable:
its pooled median would sit between two plans that no request actually took, so it fails instead of being judged.
Exit 0 when clean, 1 on an SLO breach, a regression or an unstable side.
"""

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

# A slowdown counts only when it exceeds both the ratio and the absolute floor, so ~10 ms endpoints don't flag on a
# few ms of jitter. Starting values, to be confirmed with base == head runs on GitHub-hosted runners: the spread seen
# on a laptop came from stale planner statistics after the bulk merges (fixed by their ANALYZE) plus load spikes, so
# these constants are not meant to be calibrated locally. A cold first round that persists in CI shows up as
# `unstable`, and the 4-round retry widens the spread.
RATIO = 1.3
FLOOR_MS = 5.0

OK, SLOWER, SLO_BREACH, MORE_QUERIES, NEW, REMOVED = "ok", "slower", "over SLO", "more queries", "new", "removed"
UNSTABLE_BASE, UNSTABLE_HEAD = "unstable base", "unstable head"


@dataclass(frozen=True)
class Side:
    p50: float
    slo_ms: float
    queries: int | None
    rounds: tuple[float, ...] = ()

    @property
    def unstable(self) -> bool:
        """Round medians apart by more than a slowdown would need: the side measured two plans, not one."""
        if len(self.rounds) < 2:
            return False
        low, high = min(self.rounds), max(self.rounds)
        return high > low * RATIO and high - low > FLOOR_MS


@dataclass(frozen=True)
class Row:
    scenario: str
    base: Side | None
    head: Side | None
    statuses: tuple[str, ...]

    @property
    def failing(self) -> bool:
        return any(
            status in (SLOWER, SLO_BREACH, MORE_QUERIES, UNSTABLE_BASE, UNSTABLE_HEAD) for status in self.statuses
        )


def load(paths: list[Path]) -> dict[str, Side]:
    if not paths:
        raise ValueError("no result files given")
    timings: dict[str, list[float]] = {}
    rounds: dict[str, list[float]] = {}
    meta: dict[str, tuple[float, int | None]] = {}
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
    return {
        name: Side(statistics.median(values), *meta[name], rounds=tuple(rounds[name]))
        for name, values in timings.items()
    }


def compare(base: dict[str, Side] | None, head: dict[str, Side], *, accept_regressions: bool = False) -> list[Row]:
    rows = []
    for scenario in sorted(set(head) | set(base or {})):
        before, after = (base or {}).get(scenario), head.get(scenario)
        statuses: list[str] = []
        if after is None:
            statuses.append(REMOVED)
        else:
            if after.p50 > after.slo_ms:
                statuses.append(SLO_BREACH)
            if after.unstable:
                statuses.append(UNSTABLE_HEAD)
            if base is not None and before is None:
                statuses.append(NEW)
            elif before is not None and before.unstable and not accept_regressions:
                # A slowdown against a base median that no request took means nothing either way.
                statuses.append(UNSTABLE_BASE)
            elif before is not None and not accept_regressions:
                if after.p50 > before.p50 * RATIO and after.p50 - before.p50 > FLOOR_MS:
                    statuses.append(SLOWER)
                if before.queries is not None and after.queries is not None and after.queries > before.queries:
                    statuses.append(MORE_QUERIES)
        rows.append(Row(scenario, before, after, tuple(statuses) or (OK,)))
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


def render(rows: list[Row], *, with_base: bool, accept_regressions: bool) -> str:
    failing = [row for row in rows if row.failing]
    title = "❌ Perf regression" if failing else "✅ Perf"
    lines = [f"## {title}", ""]
    if with_base:
        lines.append(
            f"p50 of all runs, base and head interleaved on the same runner. A scenario is slower when head > "
            f"{RATIO}x base **and** +{FLOOR_MS:.0f} ms. A side is unstable when its round p50s differ by as much (an unstable head fails even with the label)."
        )
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
        slo = f"{row.head.slo_ms:.0f}" if row.head else "-"
        if with_base:
            delta = f"{(row.head.p50 / row.base.p50 - 1) * 100:+.0f}%" if row.base and row.head else "-"
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
