import statistics
from collections import defaultdict
from datetime import datetime

from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest

WINDOW = 10
MIN_SAMPLES = 3
CHAINS = ("foreground", "wikidata")


def _seconds(step: dict) -> float | None:
    if step.get("state") != "succeeded" or not step.get("started_at") or not step.get("finished_at"):
        return None
    return (datetime.fromisoformat(step["finished_at"]) - datetime.fromisoformat(step["started_at"])).total_seconds()


def typical_stage_seconds(kind: str) -> dict[str, dict[str, int]] | None:
    """
    Median seconds per stage over the last WINDOW succeeded runs of `kind`, per telemetry chain, or None unless `kind`
    is full (the only kind with step telemetry). A stage with fewer than MIN_SAMPLES samples is left out.
    """
    if kind != PipelineRunRequest.Kind.FULL:
        return None
    telemetries = (
        PipelineRunRequest.objects.filter(kind=PipelineRunRequest.Kind.FULL, status=PipelineRunRequest.Status.SUCCEEDED)
        .order_by("-finished_on")
        .values_list("step_telemetry", flat=True)[:WINDOW]
    )
    samples: dict[str, dict[str, list[float]]] = {chain: defaultdict(list) for chain in CHAINS}
    for telemetry in telemetries:
        telemetry = telemetry or {}
        foreground = telemetry.get("foreground") or []
        # Before `importing_graph` existed, `importing_tree` also covered the graph import and would skew the median.
        has_graph = any(step.get("stage") == "importing_graph" for step in foreground)
        for chain in CHAINS:
            for step in telemetry.get(chain) or []:
                stage = step.get("stage")
                if stage == "importing_tree" and not has_graph:
                    continue
                seconds = _seconds(step)
                if seconds is not None:
                    samples[chain][stage].append(seconds)
    return {
        chain: {
            stage: round(statistics.median(values)) for stage, values in by_stage.items() if len(values) >= MIN_SAMPLES
        }
        for chain, by_stage in samples.items()
    }
