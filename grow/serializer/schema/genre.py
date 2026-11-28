from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from grow.openapi.documents import component_ref
from grow.serializer.model.playlist.children.criteria.output.minimum import CriteriaPlaylistMinimumSerializer
from grow.serializer.model.playlist.children.criteria.output.simple import CriteriaPlaylistSimpleSerializer
from grow.serializer.model.song.output.without_playlists import SongWithoutPlaylistsSerializer


@extend_schema_field({"type": "array", "items": component_ref("GenreTreeNode")})
class GenreTreeChildrenField(serializers.ListField):
    pass


class GenreTreeNodeSerializer(serializers.Serializer):
    name = serializers.CharField()
    children = GenreTreeChildrenField(child=serializers.DictField())


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


class GenreTreeCatalogueSerializer(serializers.Serializer):
    genre_only_tracks_count = serializers.DictField(child=serializers.IntegerField())
    genre_and_subgenres_tracks_count = serializers.DictField(child=serializers.IntegerField())


class GenrePlaylistTreeRowSerializer(CriteriaPlaylistSimpleSerializer):
    """`genre-playlists/tree/` rows are built from `.values()`: counts the list serializer lacks, no `views_count` with `artist`."""

    songs_count = serializers.IntegerField()
    catalogue = GenreTreeCatalogueSerializer()
    views_count = serializers.IntegerField(required=False)

    class Meta(CriteriaPlaylistSimpleSerializer.Meta):
        fields = [*CriteriaPlaylistSimpleSerializer.Meta.fields, "songs_count", "catalogue"]
