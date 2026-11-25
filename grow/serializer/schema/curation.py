"""Output shapes of the curation views (`grow/view/curation.py`), declared only so the OpenAPI schema can describe them."""

from typing import Any

from rest_framework import serializers
from the_music_tree_grow_contracts import load_schema

from grow.serializer.model.history.output.curation import CurationHistoryEntrySerializer
from grow.serializer.schema.common import paginated_serializer


def _labels() -> serializers.DictField:
    return serializers.DictField(child=serializers.CharField(), help_text="Name of every item id listed, keyed by id.")


class CurationRuleSerializer(serializers.Serializer):
    """A curation entry or an edge rule: `row` keeps the list's snake_case columns (the camelCase renderer skips it)."""

    uuid = serializers.UUIDField()
    row = serializers.DictField()
    created_on = serializers.DateTimeField()
    updated_on = serializers.DateTimeField(allow_null=True, help_text="Null until the first edit.")


class CurationRowRequestSerializer(serializers.Serializer):
    row = serializers.DictField(help_text="The list's columns, snake_case. A PATCH merges it into the stored row.")


CurationEntriesPageSerializer = paginated_serializer(
    "CurationEntriesPageSerializer", CurationRuleSerializer, labels=_labels()
)
CurationEdgesPageSerializer = paginated_serializer(
    "CurationEdgesPageSerializer", CurationRuleSerializer, labels=_labels()
)
CurationHistoryPageSerializer = paginated_serializer(
    "CurationHistoryPageSerializer", CurationHistoryEntrySerializer, labels=_labels()
)


class CurationColumnSpecSerializer(serializers.Serializer):
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=["item_id", "tradition_id", "entity_id", "int", "bool", "text"])
    optional = serializers.BooleanField()


class CurationListSerializer(serializers.Serializer):
    name = serializers.CharField()
    key_columns = serializers.ListField(child=serializers.CharField())
    columns = serializers.ListField(child=serializers.CharField())
    column_specs = CurationColumnSpecSerializer(many=True)
    description = serializers.CharField()
    count = serializers.IntegerField(help_text="Canonical entries in the list.")


class CurationListRuleSerializer(CurationRuleSerializer):
    list_name = serializers.CharField()


class CurationRulesSerializer(serializers.Serializer):
    results = CurationListRuleSerializer(many=True)
    edges = CurationRuleSerializer(many=True)
    labels = _labels()


class CurationStatusSerializer(serializers.Serializer):
    applied_export_on = serializers.DateTimeField(allow_null=True)
    pending_count = serializers.IntegerField()


class CurationViolationSerializer(serializers.Serializer):
    kind = serializers.CharField()
    message = serializers.CharField()
    item_ids = serializers.ListField(child=serializers.CharField())


class CurationExportConflictSerializer(serializers.Serializer):
    detail = serializers.CharField()
    violations = CurationViolationSerializer(many=True)


class WikidataResolutionsResultSerializer(serializers.Serializer):
    remapped_count = serializers.IntegerField()
    review_count = serializers.IntegerField()


class WikidataItemsResultSerializer(serializers.Serializer):
    item_count = serializers.IntegerField()


class CurationItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()


class CurationItemsSerializer(serializers.Serializer):
    results = CurationItemSerializer(many=True)


class GenreAliasTargetItemSerializer(CurationItemSerializer):
    tree = serializers.ChoiceField(choices=["canonical", "regional", "local"])


class GenreAliasTargetsSerializer(serializers.Serializer):
    published_on = serializers.DateTimeField(allow_null=True)
    curation_exported_on = serializers.DateTimeField(allow_null=True)
    results = GenreAliasTargetItemSerializer(many=True)


class CurationReviewItemSerializer(serializers.Serializer):
    rule_id = serializers.UUIDField(allow_null=True, help_text="Set for an edge rule.")
    list = serializers.CharField(allow_null=True, help_text="Null for a synthetic overview alert.")
    key = serializers.CharField(allow_null=True)
    column = serializers.CharField()
    item_id = serializers.CharField()
    reason = serializers.CharField()
    target = serializers.CharField(allow_null=True)
    evidence = serializers.DictField(allow_null=True)
    reported_on = serializers.DateTimeField()


def _openapi_compatible(node: Any) -> Any:
    """JSON Schema 2020-12 to OpenAPI 3.0: `const` has no equivalent but a one-value `enum`."""
    if isinstance(node, list):
        return [_openapi_compatible(n) for n in node]
    if not isinstance(node, dict):
        return node
    converted = {k: _openapi_compatible(v) for k, v in node.items() if k not in ("$schema", "$id", "const")}
    if "const" in node:
        converted["enum"] = [node["const"]]
    return converted


def curation_export_schema() -> dict[str, Any]:
    """The export contract.

    A raw schema rather than a serializer: the view renders with `JSONRenderer`, so its keys stay snake_case, which the
    camelize hook would otherwise rewrite.
    """
    schema = _openapi_compatible(load_schema("curation_export"))
    schema.pop("title", None)
    return schema
