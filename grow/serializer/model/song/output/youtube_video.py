from drf_spectacular.utils import extend_schema_field, inline_serializer
from rest_framework import serializers

from grow.model.song.Song import Song
from grow.youtube_regions import availability, viewer_country


class SongYoutubeVideoSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="youtube_video_id")
    unplayable_reason = serializers.CharField(source="youtube_unplayable_reason", allow_null=True)
    view_count = serializers.IntegerField(source="youtube_view_count", allow_null=True)

    availability = serializers.SerializerMethodField()

    @extend_schema_field(
        inline_serializer(
            "SongYoutubeAvailability",
            {
                "status": serializers.ChoiceField(choices=["eligible", "blocked", "unknown"]),
                "reason": serializers.CharField(allow_null=True),
                "country": serializers.CharField(allow_null=True),
            },
        )
    )
    def get_availability(self, instance):
        return availability(instance, viewer_country(self.context.get("request")))

    class Meta:
        model = Song
        fields = ["id", "unplayable_reason", "view_count", "availability"]

    def to_representation(self, instance):
        return super().to_representation(instance) if instance.youtube_video_id else None
