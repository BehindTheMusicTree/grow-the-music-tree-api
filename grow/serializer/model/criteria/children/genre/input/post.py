from rest_framework.relations import PrimaryKeyRelatedField

from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from grow.serializer.model.criteria.input.post import CriteriaPostSerializer

from .Fields import Fields


class GenrePostSerializer(CriteriaPostSerializer):
    essential_tracks = PrimaryKeyRelatedField(queryset=YoutubeTrack.objects.all(), many=True, required=False)

    class Meta(CriteriaPostSerializer.Meta):
        fields = [*CriteriaPostSerializer.Meta.fields, Fields.ESSENTIAL_TRACKS]
