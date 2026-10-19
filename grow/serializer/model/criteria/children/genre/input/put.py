from rest_framework import serializers
from rest_framework.relations import PrimaryKeyRelatedField

from grow.model.recording.Recording import Recording
from grow.serializer.model.criteria.input.put import CriteriaPutSerializer

from .Fields import Fields


class GenrePutSerializer(CriteriaPutSerializer):
    summary = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    essential_tracks = PrimaryKeyRelatedField(queryset=Recording.objects.all(), many=True, required=False)

    class Meta(CriteriaPutSerializer.Meta):
        fields = [*CriteriaPutSerializer.Meta.fields, Fields.SUMMARY, Fields.ESSENTIAL_TRACKS]
