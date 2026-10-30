from rest_framework import serializers
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide

from grow.serializer.model.criteria.input.put import CriteriaPutSerializer

from .essential_songs_input_mixin import EssentialSongsInputMixin
from .Fields import Fields


class GenrePutSerializer(EssentialSongsInputMixin, CriteriaPutSerializer):
    summary = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    side = serializers.ChoiceField(choices=CriteriaSide.choices, required=False)

    class Meta(CriteriaPutSerializer.Meta):
        fields = [
            *CriteriaPutSerializer.Meta.fields,
            Fields.SUMMARY,
            Fields.ESSENTIAL_SONGS,
            Fields.SIDE,
        ]
