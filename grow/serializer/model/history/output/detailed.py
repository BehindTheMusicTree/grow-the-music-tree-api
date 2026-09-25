from rest_framework import serializers

from grow.model.history.HistoryEntry import HistoryEntry

from .Fields import Fields


class HistoryEntryDetailedSerializer(serializers.ModelSerializer):
    class Meta:
        model = HistoryEntry
        fields = [
            Fields.UUID,
            Fields.ACTION,
            Fields.ACTOR_EMAIL,
            Fields.OLD_VALUE,
            Fields.NEW_VALUE,
            Fields.CREATED_ON,
        ]
