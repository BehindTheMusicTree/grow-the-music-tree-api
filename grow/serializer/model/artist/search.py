from rest_framework import serializers

from grow.model.artist.Artist import Artist
from grow.model.artist.Fields import Fields

SEARCH_QUERY_LEN_MIN = 2
SEARCH_QUERY_LEN_MAX = 100
SEARCH_LIMIT_DEFAULT = 10
SEARCH_LIMIT_MAX = 25


class ArtistSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=SEARCH_QUERY_LEN_MIN, max_length=SEARCH_QUERY_LEN_MAX)
    limit = serializers.IntegerField(
        required=False, default=SEARCH_LIMIT_DEFAULT, min_value=1, max_value=SEARCH_LIMIT_MAX
    )


class ArtistSearchResultSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="_name")
    matched_alias = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = Artist
        fields = [
            Fields.UUID,
            "name",
            Fields.DISAMBIGUATION,
            Fields.TYPE,
            Fields.COUNTRY,
            Fields.BEGIN_YEAR,
            Fields.END_YEAR,
            "matched_alias",
            Fields.RECORDING_COUNT,
        ]
