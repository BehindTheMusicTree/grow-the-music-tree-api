import pytest

from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from grow.pipeline_run.typical_durations import MIN_SAMPLES, WINDOW, typical_stage_seconds

pytestmark = pytest.mark.django_db


def step(stage: str, seconds: int, state: str = "succeeded") -> dict:
    return {
        "stage": stage,
        "state": state,
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": f"2026-01-01T{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}+00:00",
    }


def make_run(day: int, foreground=None, wikidata=None, kind=PipelineRunRequest.Kind.FULL) -> None:
    PipelineRunRequest.objects.create(
        kind=kind,
        status=PipelineRunRequest.Status.SUCCEEDED,
        finished_on=f"2026-02-{day:02d}T00:00:00+00:00",
        step_telemetry={"foreground": foreground or [], "wikidata": wikidata or []},
    )


def test_median_of_an_odd_and_an_even_count():
    for day, seconds in enumerate((10, 30, 20), start=1):
        make_run(day, [step("importing_songs", seconds)])
    assert typical_stage_seconds("full")["foreground"]["importing_songs"] == 20

    make_run(4, [step("importing_songs", 40)])
    assert typical_stage_seconds("full")["foreground"]["importing_songs"] == 25


def test_stage_with_too_few_samples_is_absent():
    for day in range(1, MIN_SAMPLES):
        make_run(day, [step("importing_songs", 10)])
    assert typical_stage_seconds("full") == {"foreground": {}, "wikidata": {}}


def test_failed_steps_are_ignored():
    for day in range(1, MIN_SAMPLES + 1):
        make_run(day, [step("importing_songs", 10)])
    make_run(9, [step("importing_songs", 5000, state="failed")])
    assert typical_stage_seconds("full")["foreground"]["importing_songs"] == 10


def test_only_the_last_window_runs_count():
    for day in range(1, 6):
        make_run(day, [step("importing_songs", 1000)])
    for day in range(6, 6 + WINDOW):
        make_run(day, [step("importing_songs", 10)])
    assert typical_stage_seconds("full")["foreground"]["importing_songs"] == 10


def test_non_full_kind_has_no_typical_durations():
    assert typical_stage_seconds("curation") is None


def test_importing_tree_before_importing_graph_existed_is_skipped():
    for day in range(1, MIN_SAMPLES + 1):
        make_run(day, [step("importing_tree", 900)])
    assert "importing_tree" not in typical_stage_seconds("full")["foreground"]

    for day in range(10, 10 + MIN_SAMPLES):
        make_run(day, [step("importing_tree", 60), step("importing_graph", 30)])
    typical = typical_stage_seconds("full")["foreground"]
    assert typical["importing_tree"] == 60
    assert typical["importing_graph"] == 30
