from rest_framework import serializers
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_genre_kit.criteria.track_playlist_rel.tracks_count_annotation import tracks_count_annotation
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer
from grow.serializer.model.track_playlist_rel.output.without_playlist import TrackPlaylistRelWithoutPlaylist

from .Fields import Fields


class PlaylistDetailedSerializer(EagerLoadingMixin, serializers.ModelSerializer):
    track_playlist_relations = TrackPlaylistRelWithoutPlaylist(source=Fields.TRACK_PLAYLIST_RELS_INTERNAL, many=True)
    tracks_count = serializers.IntegerField(source=Fields.TRACKS_COUNT_ANNOTATED)
    type = AppCharField(source=Fields.TYPE_LABEL_INTERNAL)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        queryset = PlaylistMinimumSerializer.setup_queryset(queryset, prefix).annotate(
            **{Fields.TRACKS_COUNT_ANNOTATED: tracks_count_annotation()}
        )
        return TrackPlaylistRelWithoutPlaylist.prefetch(queryset, f"{prefix}{Fields.TRACK_PLAYLIST_RELS_INTERNAL}")

    class Meta:
        model = Playlist
        fields = [
            Fields.UUID,
            Fields.NAME,
            Fields.TYPE_LABEL_PUBLIC,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.TRACK_PLAYLIST_RELS_PUBLIC,
            Fields.PLAY_COUNT,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
