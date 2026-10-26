from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.serializer.model.song.output.without_playlists import SongWithoutPlaylistsSerializer

from .Fields import Fields


class TrackPlaylistRelInPageSerializer(EagerLoadingMixin, AppInputSerializer, serializers.ModelSerializer):
    track = SongWithoutPlaylistsSerializer(source=f"{Fields.TRACK_INTERNAL}.song")

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        song = f"{prefix}track__song"
        return SongWithoutPlaylistsSerializer.setup_queryset(queryset.select_related(song), prefix=f"{song}__")

    class Meta:
        model = TrackPlaylistRel
        fields = [Fields.TRACK_PUBLIC, Fields.POSITION]
