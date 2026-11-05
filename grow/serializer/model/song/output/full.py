from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer

from .detailed import SongDetailedSerializer
from .SongOutputFieldKey import SongOutputFieldKey


class SongFullSerializer(SongDetailedSerializer):
    """A single song's page: the list item plus what only the detail view needs."""

    essential_genres = CriteriaMinimumSerializer(many=True)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        return super().setup_queryset(queryset, prefix).prefetch_related(f"{prefix}essential_genres")

    class Meta(SongDetailedSerializer.Meta):
        fields = [
            *SongDetailedSerializer.Meta.fields,
            SongOutputFieldKey.FIRST_RELEASE_YEAR.value,
            SongOutputFieldKey.ESSENTIAL_GENRES.value,
        ]
