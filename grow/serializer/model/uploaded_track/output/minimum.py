from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer

from grow.model.uploaded_track.UploadedTrack import UploadedTrack
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer

from .UploadedTrackOutputFieldKey import UploadedTrackOutputFieldKey


class UploadedTrackMinimumSerializer(AppInputSerializer, serializers.ModelSerializer):
    artists = ArtistMinimumSerializer(many=True)

    class Meta:
        model = UploadedTrack
        fields = [
            UploadedTrackOutputFieldKey.UUID.value,
            UploadedTrackOutputFieldKey.TITLE.value,
            UploadedTrackOutputFieldKey.ARTISTS.value,
        ]
