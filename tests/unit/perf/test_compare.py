import json
import statistics

import pytest

from perf.compare import (
    MIN_DRIFT_SCENARIOS,
    MORE_QUERIES,
    NEW,
    OK,
    REMOVED,
    SLO_BREACH,
    SLOWER,
    UNSTABLE_BASE,
    UNSTABLE_HEAD,
    Side,
    compare,
    load,
    main,
)


def _write(path, scenarios):
    path.write_text(json.dumps({"version": 1, "scenarios": scenarios}))
    return path


def _result(*timings, slo_ms=100, queries=None):
    return {"timings_ms": list(timings), "slo_ms": slo_ms, "queries": queries}


def _statuses(base, head, **kwargs):
    return {row.scenario: row.statuses for row in compare(base, head, **kwargs)}


def test_load_pools_timings_of_every_run_and_keeps_the_worst_query_count(tmp_path):
    first = _write(tmp_path / "head-1.json", {"x": _result(10, 12, queries=3)})
    second = _write(tmp_path / "head-2.json", {"x": _result(30, queries=4)})

    assert load([first, second]) == {"x": Side(p50=12, slo_ms=100, queries=4, rounds=(11, 30))}


@pytest.mark.parametrize("payload", [{"version": 2, "scenarios": {"x": {}}}, {"version": 1, "scenarios": {}}])
def test_load_rejects_files_that_are_not_perf_results(tmp_path, payload):
    path = tmp_path / "head-1.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="not a perf result file"):
        load([path])


def test_load_rejects_an_empty_file_list():
    with pytest.raises(ValueError, match="no result files"):
        load([])


def test_slowdown_must_exceed_both_the_ratio_and_the_floor():
    base = {"slow": Side(13, 150, 3), "jitter": Side(8, 30, None), "small": Side(100, 400, 4)}
    head = {"slow": Side(137, 150, 3), "jitter": Side(12, 30, None), "small": Side(120, 400, 4)}

    assert _statuses(base, head) == {"slow": (SLOWER,), "jitter": (OK,), "small": (OK,)}


def test_query_increase_fails_and_decrease_passes():
    base = {"up": Side(10, 100, 4), "down": Side(10, 100, 6)}
    head = {"up": Side(10, 100, 6), "down": Side(10, 100, 4)}

    assert _statuses(base, head) == {"up": (MORE_QUERIES,), "down": (OK,)}


def test_label_accepts_regressions_but_never_an_slo_breach():
    base = {"x": Side(10, 100, 3), "y": Side(10, 100, 3)}
    head = {"x": Side(90, 100, 9), "y": Side(110, 100, 3)}

    assert _statuses(base, head, accept_regressions=True) == {"x": (OK,), "y": (SLO_BREACH,)}


def test_scenarios_on_one_side_only_are_reported_not_failed():
    rows = compare({"gone": Side(10, 100, None)}, {"added": Side(10, 100, None)})

    assert {row.scenario: row.statuses for row in rows} == {"added": (NEW,), "gone": (REMOVED,)}
    assert not any(row.failing for row in rows)


def test_without_base_only_the_slo_is_judged():
    assert _statuses(None, {"x": Side(200, 100, 50), "y": Side(5, 100, 1)}) == {"x": (SLO_BREACH,), "y": (OK,)}


def test_main_writes_the_summary_and_exits_1_on_regression(tmp_path):
    base = _write(tmp_path / "base-1.json", {"x": _result(10, 10, 10, queries=2)})
    head = _write(tmp_path / "head-1.json", {"x": _result(50, 50, 50, queries=2)})
    summary = tmp_path / "summary.md"

    assert main(["--base", str(base), "--head", str(head), "--summary", str(summary)]) == 1
    report = summary.read_text()
    assert "❌ Perf regression" in report
    assert "| x | 10.0 | 50.0 | +400% | 10 | 50 | 2 | 100 | **slower** |" in report


def test_main_exits_0_when_clean(tmp_path):
    head = _write(tmp_path / "head-1.json", {"x": _result(10, queries=2)})

    assert main(["--head", str(head)]) == 0


def test_a_side_whose_round_medians_disagree_is_unstable():
    assert Side(668, 150, 3, rounds=(1170, 178)).unstable
    assert not Side(180, 150, 3, rounds=(178, 198)).unstable  # within RATIO
    assert not Side(3, 150, 3, rounds=(2, 4)).unstable  # within FLOOR_MS
    assert not Side(30, 150, 3, rounds=(30,)).unstable


def test_an_unstable_head_fails_even_against_a_matching_base():
    base = {"x": Side(100, 1000, 3, rounds=(100, 100))}
    head = {"x": Side(100, 1000, 3, rounds=(30, 170))}

    assert _statuses(base, head) == {"x": (UNSTABLE_HEAD,)}


def test_an_unstable_base_replaces_the_slowdown_verdict():
    base = {"x": Side(100, 1000, 3, rounds=(30, 170))}
    head = {"x": Side(200, 1000, 3, rounds=(200, 200))}

    assert _statuses(base, head) == {"x": (UNSTABLE_BASE,)}
    assert _statuses(base, head, accept_regressions=True) == {"x": (OK,)}


def test_main_fails_on_a_bimodal_head(tmp_path):
    rounds = [
        _write(tmp_path / f"head-{i}.json", {"x": _result(ms, ms, queries=2)}) for i, ms in enumerate((1170, 178))
    ]
    summary = tmp_path / "summary.md"

    assert main(["--head", *map(str, rounds), "--summary", str(summary), "--accept-regressions"]) == 1
    assert "| 1170 / 178 |" in summary.read_text()


def test_pending_calibration_preserves_relative_and_stability_gates(tmp_path):
    base = {"x": Side(10, None, 2)}
    assert _statuses(base, {"x": Side(30, None, 3)}) == {"x": (SLOWER, MORE_QUERIES)}
    assert _statuses(None, {"x": Side(30, None, 2, rounds=(10, 50))}) == {"x": (UNSTABLE_HEAD,)}
    result = _result(10, queries=2)
    result["slo_ms"] = None
    head = _write(tmp_path / "head-1.json", {"x": result})
    summary = tmp_path / "summary.md"
    assert main(["--head", str(head), "--summary", str(summary)]) == 0
    assert "pending calibration" in summary.read_text()


def test_calibration_cannot_remove_an_existing_ceiling():
    assert _statuses({"x": Side(10, 100, 2)}, {"x": Side(10, None, 2)}) == {"x": (SLO_BREACH,)}


def _fleet(rounds_by_scenario, **kwargs):
    """Sides of many scenarios, with the drift of each round estimated like load() does."""
    count = len(next(iter(rounds_by_scenario.values())))
    usual = {name: statistics.median(values) for name, values in rounds_by_scenario.items()}
    drift = tuple(
        statistics.median(values[i] / usual[name] for name, values in rounds_by_scenario.items()) for i in range(count)
    )
    return {
        name: Side(statistics.median(values), 1000, 3, rounds=tuple(values), drift=drift, **kwargs)
        for name, values in rounds_by_scenario.items()
    }


def _steady(count=MIN_DRIFT_SCENARIOS + 2):
    return {f"s{i}": [50.0 + i, 50.0 + i, 50.0 + i, 50.0 + i] for i in range(count)}


def test_drift_shared_by_base_and_head_flags_nothing():
    stepped = {
        name: [v * f for v, f in zip(values, (1, 1.25, 1.25, 1.25), strict=True)] for name, values in _steady().items()
    }
    stepped["issue"] = [57, 71, 74, 64]  # criteria-detail Latin (alternating), head side of the incident

    assert set(_statuses(_fleet(stepped), _fleet(stepped)).values()) == {(OK,)}


def test_a_scenario_that_alone_changes_plan_is_unstable_among_stable_ones():
    flipped = _steady()
    flipped["s0"] = [50.0, 50.0, 90.0, 90.0]

    statuses = _statuses(_fleet(_steady()), _fleet(flipped))

    assert statuses["s0"] == (UNSTABLE_HEAD, SLOWER)
    assert {k: v for k, v in statuses.items() if k != "s0"} == {k: (OK,) for k in statuses if k != "s0"}


def test_a_uniform_head_slowdown_is_still_slower_everywhere():
    slow = {name: [v * 1.6 for v in values] for name, values in _steady().items()}

    assert set(_statuses(_fleet(_steady()), _fleet(slow)).values()) == {(SLOWER,)}


def test_noise_without_a_gap_between_rounds_is_not_unstable():
    side = Side(24, 1000, 3, rounds=(21, 28, 21, 26))

    assert not side.unstable


def test_unstable_needs_a_gap_not_just_a_wide_range():
    assert Side(100, 1000, 3, rounds=(100, 100, 100, 300)).unstable
    assert not Side(100, 1000, 3, rounds=(100, 120, 140, 160, 180)).unstable


def test_few_scenarios_keep_the_raw_rounds(tmp_path):
    path = _write(tmp_path / "head-1.json", {"x": _result(10, queries=2)})
    _write(tmp_path / "head-2.json", {"x": _result(20, queries=2)})

    side = load([path, tmp_path / "head-2.json"])["x"]

    assert side.drift == () and side.settled == side.rounds == (10, 20)


def test_load_orders_rounds_by_number_and_rejects_other_names(tmp_path):
    paths = [_write(tmp_path / f"head-{n}.json", {"x": _result(n, queries=2)}) for n in (10, 9, 2)]

    assert load(paths)["x"].rounds == (2, 9, 10)
    other = _write(tmp_path / "result.json", {"x": _result(1, queries=2)})
    with pytest.raises(ValueError, match="round number"):
        load([other])


def test_base_and_head_must_cover_the_same_rounds():
    with pytest.raises(ValueError, match="different number of rounds"):
        compare({"x": Side(10, 100, 2, rounds=(10, 10))}, {"x": Side(10, 100, 2, rounds=(10,))})


def test_load_estimates_drift_per_round_and_judges_a_scenario_missing_a_round_raw(tmp_path):
    factors = (1.0, 1.2)
    for n, factor in enumerate(factors, start=1):
        scenarios = {f"s{i}": _result((60 + i) * factor, queries=2) for i in range(MIN_DRIFT_SCENARIOS)}
        if n == 2:
            scenarios["late"] = _result(30, queries=2)
        _write(tmp_path / f"head-{n}.json", scenarios)

    sides = load([tmp_path / "head-1.json", tmp_path / "head-2.json"])

    assert sides["s0"].drift == pytest.approx((1 / 1.1, 1.2 / 1.1), abs=1e-3)
    assert sides["late"].drift == () and sides["late"].rounds == (30,)
    assert not any(side.unstable for side in sides.values())
