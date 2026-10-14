from rest_framework.relations import PrimaryKeyRelatedField

from grow.model.recording.Recording import Recording
from grow.serializer.model.criteria.input.put import CriteriaPutSerializer

from .Fields import Fields


class GenrePutSerializer(CriteriaPutSerializer):
    essential_tracks = PrimaryKeyRelatedField(queryset=Recording.objects.all(), many=True, required=False)

    class Meta(CriteriaPutSerializer.Meta):
        fields = [*CriteriaPutSerializer.Meta.fields, Fields.ESSENTIAL_TRACKS]
