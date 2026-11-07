from functools import cached_property

from rest_framework import serializers

from grow.genre_music.summary import genre_playlist_summaries
from grow.serializer.model.criteria.output.detailed import CriteriaDetailedSerializer
from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer


class GenreDetailedSerializer(CriteriaDetailedSerializer):
    catalogue = serializers.SerializerMethodField()
    criteria_playlist = serializers.SerializerMethodField()
    tracks_count = serializers.SerializerMethodField()

    @cached_property
    def summary(self):
        playlist_id = self.instance.criteria_playlist.pk
        return genre_playlist_summaries({playlist_id})[playlist_id]

    def get_catalogue(self, instance):
        return self.summary["catalogue"]

    def get_tracks_count(self, instance):
        scopes = self.summary["catalogue"]["genre_and_subgenres_tracks_count"]
        return scopes.get("canonical", scopes["all"])

    def get_criteria_playlist(self, instance):
        identity = CriteriaPlaylistMinimumSerializer(instance.criteria_playlist, context=self.context).data
        return {
            **identity,
            "genre_only_tracks_count": self.summary["genre_only_tracks_count"],
            "genre_and_subgenres_tracks_count": self.summary["genre_and_subgenres_tracks_count"],
        }

    class Meta(CriteriaDetailedSerializer.Meta):
        fields = [*CriteriaDetailedSerializer.Meta.fields, "catalogue"]
