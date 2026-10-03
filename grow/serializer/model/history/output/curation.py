from rest_framework import serializers

from .detailed import HistoryEntryDetailedSerializer


class CurationHistoryEntrySerializer(HistoryEntryDetailedSerializer):
    entry = serializers.UUIDField(source="content_uuid")

    class Meta(HistoryEntryDetailedSerializer.Meta):
        fields = [*HistoryEntryDetailedSerializer.Meta.fields, "entry"]
