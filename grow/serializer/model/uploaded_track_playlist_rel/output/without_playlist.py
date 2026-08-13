from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer

from grow.model.uploaded_track_playlist_rel.UploadedTrackPlaylistRel import UploadedTrackPlaylistRel
from grow.serializer.model.uploaded_track.output.detailed import UploadedTrackDetailedSerializer

from .Fields import Fields


class UploadedTrackPlaylistRelWithoutPlaylist(AppInputSerializer, serializers.ModelSerializer):
    uploaded_track = UploadedTrackDetailedSerializer()

    class Meta:
        model = UploadedTrackPlaylistRel
        fields = [
            Fields.UPLOADED_TRACK_PUBLIC,
            Fields.POSITION,
        ]
