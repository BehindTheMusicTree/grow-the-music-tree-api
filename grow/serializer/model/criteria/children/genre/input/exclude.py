from rest_framework import serializers
from the_music_tree_grow_contracts.curation_lists import EXCLUDED_GENRE_LISTS


class GenreExcludeSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=list(EXCLUDED_GENRE_LISTS))
