from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.serializer.model.youtube_track.output.detailed import YoutubeTrackDetailedSerializer

from .Fields import Fields


class TrackPlaylistRelWithoutPlaylist(AppInputSerializer, serializers.ModelSerializer):
    track = serializers.SerializerMethodField()

    def get_track(self, obj):
        return YoutubeTrackDetailedSerializer(obj.track).data

    class Meta:
        model = TrackPlaylistRel
        fields = [
            Fields.TRACK_PUBLIC,
            Fields.POSITION,
        ]
