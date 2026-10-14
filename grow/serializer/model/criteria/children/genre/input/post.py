from rest_framework.relations import PrimaryKeyRelatedField

from grow.model.recording.Recording import Recording
from grow.serializer.model.criteria.input.post import CriteriaPostSerializer

from .Fields import Fields


class GenrePostSerializer(CriteriaPostSerializer):
    essential_tracks = PrimaryKeyRelatedField(queryset=Recording.objects.all(), many=True, required=False)

    class Meta(CriteriaPostSerializer.Meta):
        fields = [*CriteriaPostSerializer.Meta.fields, Fields.ESSENTIAL_TRACKS]
