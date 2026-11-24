from datetime import UTC
from itertools import pairwise
from typing import Any

from rest_framework import serializers

from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest

WIKIDATA_STAGES = (
    "ingesting_geohistory",
    "ingesting_wikidata",
    "building_wikidata_silver",
    "building_geohistory_silver",
    "resolving_wikidata_silver",
    "anchoring_wikidata_silver",
)


class StepSerializer(serializers.Serializer):
    started_at = serializers.DateTimeField(default_timezone=UTC)
    finished_at = serializers.DateTimeField(allow_null=True, default_timezone=UTC)
    state = serializers.ChoiceField(choices=("running", "succeeded", "failed", "cancelled"))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        finished = attrs["finished_at"]
        if (finished is None) != (attrs["state"] == "running"):
            raise serializers.ValidationError("Only a running step can have an unknown finish time")
        if finished is not None and finished < attrs["started_at"]:
            raise serializers.ValidationError("A step cannot finish before it starts")
        return attrs


class ForegroundStepSerializer(StepSerializer):
    stage = serializers.ChoiceField(choices=PipelineRunRequest.Stage.values)


class WikidataStepSerializer(StepSerializer):
    stage = serializers.ChoiceField(choices=WIKIDATA_STAGES)


class WikidataRetrySerializer(serializers.Serializer):
    attempt = serializers.IntegerField(min_value=1)
    reason = serializers.ChoiceField(choices=("http", "transport", "timeout"))
    http_status = serializers.IntegerField(min_value=100, max_value=599, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if (attrs["reason"] == "http") != (attrs["http_status"] is not None):
            raise serializers.ValidationError("Only an HTTP retry has a status code")
        return attrs


class StepTelemetrySerializer(serializers.Serializer):
    variant = serializers.ChoiceField(choices=("bronze_only", "legacy_silver", "split_silver"), required=False)
    foreground = ForegroundStepSerializer(many=True, max_length=len(PipelineRunRequest.Stage.values), required=False)
    wikidata = WikidataStepSerializer(many=True, max_length=len(WIKIDATA_STAGES), required=False)
    wikidata_retry = WikidataRetrySerializer(allow_null=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        for chain in ("foreground", "wikidata"):
            steps = attrs.get(chain, [])
            if len({step["stage"] for step in steps}) != len(steps):
                raise serializers.ValidationError({chain: "Each stage can only appear once"})
            for previous, current in pairwise(steps):
                if previous["finished_at"] is None or previous["finished_at"] > current["started_at"]:
                    raise serializers.ValidationError({chain: "Steps must be ordered and cannot overlap"})
        return attrs


def check_chains_extend(stored: dict[str, Any] | None, update: dict[str, Any]) -> None:
    """A snapshot may only append steps or finish a running one: it never drops or rewrites finished history."""
    for chain in ("foreground", "wikidata"):
        if chain not in update or not stored:
            continue
        old, new = stored[chain], update[chain]
        rewritten = len(new) < len(old) or any(
            before["state"] != "running" and before != after for before, after in zip(old, new, strict=False)
        )
        if rewritten or any(
            before["state"] == "running"
            and (before["stage"], before["started_at"]) != (after["stage"], after["started_at"])
            for before, after in zip(old, new, strict=False)
        ):
            raise serializers.ValidationError({chain: "A snapshot cannot drop or rewrite earlier steps"})
