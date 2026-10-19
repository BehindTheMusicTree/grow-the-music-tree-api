from rest_framework import serializers
from the_music_tree_genre_kit.track.YoutubeUnplayableReason import YoutubeUnplayableReason

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.recording.Recording import Recording


class RecordingAssignGenreSerializer(serializers.Serializer):
    recordings = serializers.SlugRelatedField(
        queryset=Recording.objects.all(), slug_field="uuid", many=True, allow_empty=False
    )
    genre = serializers.SlugRelatedField(queryset=Genre.objects.all(), slug_field="uuid", allow_null=True)

    def validate_recordings(self, recordings):
        if len({recording.uuid for recording in recordings}) != len(recordings):
            raise serializers.ValidationError("Each recording can only appear once")
        return recordings


class RecordingYoutubePatchSerializer(serializers.Serializer):
    youtube_video_id = serializers.CharField(max_length=32, allow_null=True, required=False)
    youtube_unplayable_reason = serializers.ChoiceField(
        choices=YoutubeUnplayableReason.choices, allow_null=True, required=False
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide youtubeVideoId and/or youtubeUnplayableReason")
        return attrs


class RecordingSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, default="")
    genreless = serializers.BooleanField(required=False, default=False)
    cursor = serializers.UUIDField(required=False, allow_null=True, default=None)
