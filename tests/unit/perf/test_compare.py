import json

import pytest

from perf.compare import MORE_QUERIES, NEW, OK, REMOVED, SLO_BREACH, SLOWER, Side, compare, load, main


def _write(path, scenarios):
    path.write_text(json.dumps({"version": 1, "scenarios": scenarios}))
    return path


def _result(*timings, slo_ms=100, queries=None):
    return {"timings_ms": list(timings), "slo_ms": slo_ms, "queries": queries}


def _statuses(base, head, **kwargs):
    return {row.scenario: row.statuses for row in compare(base, head, **kwargs)}


def test_load_pools_timings_of_every_run_and_keeps_the_worst_query_count(tmp_path):
    first = _write(tmp_path / "a.json", {"x": _result(10, 12, queries=3)})
    second = _write(tmp_path / "b.json", {"x": _result(30, queries=4)})

    assert load([first, second]) == {"x": Side(p50=12, slo_ms=100, queries=4)}


@pytest.mark.parametrize("payload", [{"version": 2, "scenarios": {"x": {}}}, {"version": 1, "scenarios": {}}])
def test_load_rejects_files_that_are_not_perf_results(tmp_path, payload):
    path = tmp_path / "bad.json"
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
    base = _write(tmp_path / "base.json", {"x": _result(10, 10, 10, queries=2)})
    head = _write(tmp_path / "head.json", {"x": _result(50, 50, 50, queries=2)})
    summary = tmp_path / "summary.md"

    assert main(["--base", str(base), "--head", str(head), "--summary", str(summary)]) == 1
    report = summary.read_text()
    assert "❌ Perf regression" in report
    assert "| x | 10.0 | 50.0 | +400% | 2 | 100 | **slower** |" in report


def test_main_exits_0_when_clean(tmp_path):
    head = _write(tmp_path / "head.json", {"x": _result(10, queries=2)})

    assert main(["--head", str(head)]) == 0
