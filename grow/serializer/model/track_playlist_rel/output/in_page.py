from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.serializer.model.youtube_track.output.without_playlists import YoutubeTrackWithoutPlaylistsSerializer

from .Fields import Fields


class TrackPlaylistRelInPageSerializer(EagerLoadingMixin, AppInputSerializer, serializers.ModelSerializer):
    track = YoutubeTrackWithoutPlaylistsSerializer(source=f"{Fields.TRACK_INTERNAL}.youtubetrack")

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        youtube_track = f"{prefix}track__youtubetrack"
        return YoutubeTrackWithoutPlaylistsSerializer.setup_queryset(
            queryset.select_related(youtube_track), prefix=f"{youtube_track}__"
        )

    class Meta:
        model = TrackPlaylistRel
        fields = [Fields.TRACK_PUBLIC, Fields.POSITION]
