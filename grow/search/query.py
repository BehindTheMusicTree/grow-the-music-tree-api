from rest_framework import serializers

SEARCH_QUERY_LEN_MIN = 2
SEARCH_QUERY_LEN_MAX = 100


def search_limit(default: int, maximum: int) -> serializers.IntegerField:
    return serializers.IntegerField(required=False, default=default, min_value=1, max_value=maximum)


class SearchQuerySerializer(serializers.Serializer):
    """The `q` contract shared by every search endpoint; each subclass adds its own `limit = search_limit(...)`."""

    q = serializers.CharField(min_length=SEARCH_QUERY_LEN_MIN, max_length=SEARCH_QUERY_LEN_MAX)
