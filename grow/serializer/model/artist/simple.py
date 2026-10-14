from django.db.models import Count
from rest_framework import serializers
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin

from grow.model.artist.Artist import Artist
from grow.serializer.model.album.minimum import AlbumMinimumSerializer

from .Fields import Fields


class ArtistSimpleSerializer(EagerLoadingMixin, serializers.ModelSerializer):
    albums = AlbumMinimumSerializer(many=True)
    tracks_count = serializers.IntegerField(source=Fields.TRACKS_COUNT_ANNOTATED)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        return queryset.prefetch_related(f"{prefix}{Fields.ALBUMS}__{Fields.ALBUM_ARTISTS}").annotate(
            **{Fields.TRACKS_COUNT_ANNOTATED: Count(f"{prefix}{Fields.TRACKS_RELATED_NAME}", distinct=True)}
        )

    class Meta:
        model = Artist
        fields = [
            Fields.UUID,
            Fields.NAME_PUBLIC,
            Fields.ALBUMS,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.CREATED_ON,
        ]
