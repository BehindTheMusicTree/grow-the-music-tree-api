from rest_framework import serializers
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.serializer.model.playlist.base.output.Fields import Fields as AvailableFields


class Fields:
    UUID = AvailableFields.UUID
    NAME = AvailableFields.NAME


class PlaylistMinimumSerializer(EagerLoadingMixin, serializers.ModelSerializer):
    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        # `name` and `type` read through whichever typed child the playlist has.
        return queryset.select_related(
            f"{prefix}manual_playlist", f"{prefix}criteria_playlist__criteria", f"{prefix}criteria_playlist__type"
        )

    class Meta:
        model = Playlist
        fields = [Fields.UUID, Fields.NAME]
