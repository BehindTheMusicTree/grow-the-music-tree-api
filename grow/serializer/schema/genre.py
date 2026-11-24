from rest_framework import serializers

from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer
from grow.serializer.model.song.output.without_playlists import SongWithoutPlaylistsSerializer


class GenreTreeNodeSerializer(serializers.Serializer):
    name = serializers.CharField()
    children = serializers.ListField(
        child=serializers.DictField(), help_text="Nodes of this same shape (`name`, `children`), recursively."
    )


class GenreLinkSuggestionSerializer(SongWithoutPlaylistsSerializer):
    shared_artists = serializers.IntegerField(help_text="Artists the song shares with the genre's songs.")

    class Meta(SongWithoutPlaylistsSerializer.Meta):
        fields = [*SongWithoutPlaylistsSerializer.Meta.fields, "shared_artists"]


class GenreAliasConflictSerializer(serializers.Serializer):
    detail = serializers.CharField()
    paths = serializers.ListField(child=serializers.ListField(child=serializers.CharField()))


class GenreAliasCountsSerializer(serializers.Serializer):
    songs = serializers.IntegerField()
    essential_songs = serializers.IntegerField()
    children = serializers.IntegerField()


class GenreCataloguePlaylistSerializer(CriteriaPlaylistMinimumSerializer):
    name = serializers.CharField()
    genre_only_tracks_count = serializers.DictField(child=serializers.IntegerField())
    genre_and_subgenres_tracks_count = serializers.DictField(child=serializers.IntegerField())

    class Meta(CriteriaPlaylistMinimumSerializer.Meta):  # type: ignore[name-defined]
        fields = [
            *CriteriaPlaylistMinimumSerializer.Meta.fields,  # type: ignore[attr-defined]
            "genre_only_tracks_count",
            "genre_and_subgenres_tracks_count",
        ]
