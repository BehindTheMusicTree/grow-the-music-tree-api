from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce
from rest_framework import serializers
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_genre_kit.criteria.track_playlist_rel.Fields import Fields as TrackPlaylistRelFields
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.serializer.model.playlist.base.output.Fields import Fields as AvailableFields
from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer


class Fields:
    UUID = AvailableFields.UUID
    TRACKS_COUNT_INTERNAL = AvailableFields.TRACKS_COUNT_INTERNAL
    TRACKS_COUNT_PUBLIC = AvailableFields.TRACKS_COUNT_PUBLIC
    NAME = AvailableFields.NAME
    TYPE_LABEL_INTERNAL = AvailableFields.TYPE_LABEL_INTERNAL
    TYPE_LABEL_PUBLIC = AvailableFields.TYPE_LABEL_PUBLIC
    CREATED_ON = AvailableFields.CREATED_ON


def tracks_count_annotation() -> dict[str, Coalesce]:
    # Correlated, so only the page's rows are counted: a joined COUNT ... GROUP BY aggregates every playlist first.
    rels = TrackPlaylistRel._default_manager.filter(**{TrackPlaylistRelFields.PLAYLIST: OuterRef("pk")})
    count = (
        rels.order_by()
        .values(TrackPlaylistRelFields.PLAYLIST)
        .annotate(count=Count(TrackPlaylistRelFields.TRACK_INTERNAL, distinct=True))
    )
    return {AvailableFields.TRACKS_COUNT_ANNOTATED: Coalesce(Subquery(count.values("count")), 0)}


class PlaylistSimpleSerializer(EagerLoadingMixin, serializers.ModelSerializer):
    type = AppCharField(source=Fields.TYPE_LABEL_INTERNAL)
    tracks_count = serializers.IntegerField(source=AvailableFields.TRACKS_COUNT_ANNOTATED)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        return PlaylistMinimumSerializer.setup_queryset(queryset, prefix).annotate(**tracks_count_annotation())

    class Meta:
        model = Playlist
        fields = [
            Fields.UUID,
            Fields.NAME,
            Fields.TYPE_LABEL_PUBLIC,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.CREATED_ON,
        ]
