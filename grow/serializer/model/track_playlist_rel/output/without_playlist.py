from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer

from grow.model.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from grow.serializer.model.youtube_track.output.detailed import YoutubeTrackDetailedSerializer

from .Fields import Fields


class TrackPlaylistRelWithoutPlaylist(AppInputSerializer, serializers.ModelSerializer):
    track = serializers.SerializerMethodField()

    def get_track(self, obj):
        concrete = obj.track.resolve_concrete()
        if isinstance(concrete, YoutubeTrack):
            return YoutubeTrackDetailedSerializer(concrete).data
        raise NotImplementedError(f"No detailed serializer for track type {type(concrete).__name__}")

    class Meta:
        model = TrackPlaylistRel
        fields = [
            Fields.TRACK_PUBLIC,
            Fields.POSITION,
        ]
