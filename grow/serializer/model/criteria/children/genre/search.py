from rest_framework import serializers
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName

from grow.search.query import SearchQuerySerializer, search_limit

SEARCH_LIMIT_DEFAULT = 8
SEARCH_LIMIT_MAX = 25


class GenreSearchQuerySerializer(SearchQuerySerializer):
    limit = search_limit(SEARCH_LIMIT_DEFAULT, SEARCH_LIMIT_MAX)
    tree_name = serializers.ChoiceField(choices=CriteriaTreeName.choices, required=False, default=None)


class GenreSearchRootSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(source="root_uuid")
    name = serializers.CharField(source="root_name")


class GenreSearchResultSerializer(serializers.Serializer):
    """Built from `GenreManager.search` rows. `root` tells apart same-named genres and places the hit in the tree."""

    uuid = serializers.UUIDField()
    name = serializers.CharField()
    tree_name = serializers.CharField()
    genre_playlist_uuid = serializers.UUIDField(allow_null=True)
    is_umbrella = serializers.BooleanField()
    root = GenreSearchRootSerializer(source="*")
    views_count = serializers.IntegerField()
