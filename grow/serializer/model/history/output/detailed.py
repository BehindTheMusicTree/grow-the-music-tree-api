from rest_framework import serializers

from grow.model.history.HistoryEntry import HistoryEntry

from .Fields import Fields


class HistoryEntryDetailedSerializer(serializers.ModelSerializer):
    actor_pseudo = serializers.SerializerMethodField()

    class Meta:
        model = HistoryEntry
        fields = [
            Fields.UUID,
            Fields.ACTION,
            Fields.ACTOR_PSEUDO,
            Fields.OLD_VALUE,
            Fields.NEW_VALUE,
            Fields.CREATED_ON,
        ]

    def get_actor_pseudo(self, entry: HistoryEntry) -> str | None:
        # A profile-less actor raises on purpose: every admin must get a pseudo via `set_user_pseudo`.
        return entry.actor.profile.pseudo if entry.actor else None
