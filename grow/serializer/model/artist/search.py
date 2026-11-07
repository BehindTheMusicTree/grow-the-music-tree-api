from rest_framework import serializers

from grow.model.artist.Artist import Artist
from grow.model.artist.Fields import Fields
from grow.search.query import SearchQuerySerializer, search_limit

SEARCH_LIMIT_DEFAULT = 10
SEARCH_LIMIT_MAX = 25


class ArtistSearchQuerySerializer(SearchQuerySerializer):
    limit = search_limit(SEARCH_LIMIT_DEFAULT, SEARCH_LIMIT_MAX)


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
