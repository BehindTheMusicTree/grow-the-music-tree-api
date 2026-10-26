from rest_framework import serializers

from grow.model.song.Song import Song


class SongYoutubeVideoSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="youtube_video_id")
    unplayable_reason = serializers.CharField(source="youtube_unplayable_reason", allow_null=True)

    class Meta:
        model = Song
        fields = ["id", "unplayable_reason"]

    def to_representation(self, instance):
        return super().to_representation(instance) if instance.youtube_video_id else None
