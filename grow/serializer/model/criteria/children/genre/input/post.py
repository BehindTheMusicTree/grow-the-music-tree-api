from grow.serializer.model.criteria.input.post import CriteriaPostSerializer

from .essential_songs_input_mixin import EssentialSongsInputMixin
from .Fields import Fields


class GenrePostSerializer(EssentialSongsInputMixin, CriteriaPostSerializer):
    class Meta(CriteriaPostSerializer.Meta):
        fields = [*CriteriaPostSerializer.Meta.fields, Fields.ESSENTIAL_SONGS]
