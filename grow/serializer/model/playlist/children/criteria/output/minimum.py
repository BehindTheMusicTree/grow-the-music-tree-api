from rest_framework import serializers
from the_music_tree_api_kit.uuid.Fields import Fields as UuidFields

from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.children.criteria.Fields import Fields as ModelFields


class CriteriaPlaylistMinimumSerializer(serializers.ModelSerializer):
    class Meta:
        model = CriteriaPlaylist
        fields = [UuidFields.UUID, ModelFields.NAME]
