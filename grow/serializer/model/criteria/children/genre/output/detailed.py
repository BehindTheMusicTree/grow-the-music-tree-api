from functools import cached_property

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from grow.genre_music.summary import genre_playlist_summaries
from grow.serializer.model.criteria.output.detailed import CriteriaDetailedSerializer
from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer
from grow.serializer.schema.genre import GenreCataloguePlaylistSerializer


class GenreDetailedSerializer(CriteriaDetailedSerializer):
    catalogue = serializers.SerializerMethodField()
    criteria_playlist = serializers.SerializerMethodField()
    tracks_count = serializers.SerializerMethodField()

    @cached_property
    def summary(self):
        playlist_id = self.instance.criteria_playlist.pk
        return genre_playlist_summaries({playlist_id})[playlist_id]

    @extend_schema_field(serializers.DictField())
    def get_catalogue(self, instance):
        return self.summary["catalogue"]

    @extend_schema_field(serializers.IntegerField())
    def get_tracks_count(self, instance):
        scopes = self.summary["catalogue"]["genre_and_subgenres_tracks_count"]
        return scopes.get("global", scopes["all"])

    @extend_schema_field(GenreCataloguePlaylistSerializer)
    def get_criteria_playlist(self, instance):
        identity = CriteriaPlaylistMinimumSerializer(instance.criteria_playlist, context=self.context).data
        return {
            **identity,
            "genre_only_tracks_count": self.summary["genre_only_tracks_count"],
            "genre_and_subgenres_tracks_count": self.summary["genre_and_subgenres_tracks_count"],
        }

    class Meta(CriteriaDetailedSerializer.Meta):
        fields = [*CriteriaDetailedSerializer.Meta.fields, "catalogue"]
