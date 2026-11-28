"""Output shapes of the curation views (`grow/view/curation.py`), declared only so the OpenAPI schema can describe them."""

from rest_framework import serializers

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
    tree = serializers.ChoiceField(choices=["global", "regional", "local"])


class GenreAliasTargetsSerializer(serializers.Serializer):
    published_on = serializers.DateTimeField(allow_null=True)
    curation_exported_on = serializers.DateTimeField(allow_null=True)
    results = GenreAliasTargetItemSerializer(many=True)


class CurationReviewItemSerializer(serializers.Serializer):
    rule_id = serializers.CharField(allow_null=True, help_text="An edge rule's decision_id.")
    list = serializers.CharField(allow_null=True, help_text="Null for an alert about no list or rule.")
    key = serializers.CharField(allow_null=True)
    column = serializers.CharField()
    item_id = serializers.CharField()
    reason = serializers.CharField()
    target = serializers.CharField(allow_null=True)
    evidence = serializers.DictField(allow_null=True)
    reported_on = serializers.DateTimeField()
