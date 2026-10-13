from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.serializer.model.recording.output.without_playlists import RecordingWithoutPlaylistsSerializer

from .Fields import Fields


class TrackPlaylistRelInPageSerializer(EagerLoadingMixin, AppInputSerializer, serializers.ModelSerializer):
    track = RecordingWithoutPlaylistsSerializer(source=f"{Fields.TRACK_INTERNAL}.recording")

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        recording = f"{prefix}track__recording"
        return RecordingWithoutPlaylistsSerializer.setup_queryset(
            queryset.select_related(recording), prefix=f"{recording}__"
        )

    class Meta:
        model = TrackPlaylistRel
        fields = [Fields.TRACK_PUBLIC, Fields.POSITION]
