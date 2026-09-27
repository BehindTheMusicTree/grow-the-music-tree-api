from rest_framework import serializers

from grow.model.youtube_track.YoutubeTrack import YoutubeTrack

from .YoutubeTrackOutputFieldKey import YoutubeTrackOutputFieldKey


class YoutubeTrackMinimumSerializer(serializers.ModelSerializer):
    class Meta:
        model = YoutubeTrack
        fields = [YoutubeTrackOutputFieldKey.UUID.value, YoutubeTrackOutputFieldKey.TITLE.value]
