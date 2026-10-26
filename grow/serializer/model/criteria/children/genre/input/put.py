from rest_framework import serializers

from grow.serializer.model.criteria.input.put import CriteriaPutSerializer

from .essential_songs_input_mixin import EssentialSongsInputMixin
from .Fields import Fields


class GenrePutSerializer(EssentialSongsInputMixin, CriteriaPutSerializer):
    summary = serializers.CharField(allow_blank=True, allow_null=True, required=False)

    class Meta(CriteriaPutSerializer.Meta):
        fields = [
            *CriteriaPutSerializer.Meta.fields,
            Fields.SUMMARY,
            Fields.ESSENTIAL_SONGS,
        ]
