from rest_framework import serializers

from grow.curation.lists import EXCLUDED_GENRE_LISTS


class GenreExcludeSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=list(EXCLUDED_GENRE_LISTS))
