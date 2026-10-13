from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin

from grow.model.recording.Recording import Recording
from grow.serializer.model.album.minimum import AlbumMinimumSerializer
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer

from .RecordingOutputFieldKey import RecordingOutputFieldKey
from .youtube_video import RecordingYoutubeVideoSerializer


class RecordingWithoutPlaylistsSerializer(EagerLoadingMixin, AppInputSerializer, serializers.ModelSerializer):
    artists = ArtistMinimumSerializer(many=True)
    album = AlbumMinimumSerializer()
    genre = CriteriaMinimumSerializer()
    youtube_video = RecordingYoutubeVideoSerializer(source="*")

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        return queryset.select_related(f"{prefix}album", f"{prefix}genre").prefetch_related(f"{prefix}artists")

    class Meta:
        model = Recording
        fields = [
            RecordingOutputFieldKey.UUID.value,
            RecordingOutputFieldKey.RELATIVE_URL.value,
            RecordingOutputFieldKey.TITLE.value,
            RecordingOutputFieldKey.ARTISTS.value,
            RecordingOutputFieldKey.ALBUM.value,
            RecordingOutputFieldKey.TRACK_NUMBER.value,
            RecordingOutputFieldKey.GENRE.value,
            RecordingOutputFieldKey.RATING.value,
            RecordingOutputFieldKey.LANGUAGE.value,
            RecordingOutputFieldKey.PLAY_COUNT.value,
            RecordingOutputFieldKey.YOUTUBE_VIDEO.value,
            # Legacy flat YouTube fields, removed once consumers read youtube_video.
            RecordingOutputFieldKey.YOUTUBE_VIDEO_ID.value,
            RecordingOutputFieldKey.MUSICBRAINZ_RECORDING_ID.value,
            RecordingOutputFieldKey.YOUTUBE_UNPLAYABLE_REASON.value,
            RecordingOutputFieldKey.CREATED_ON.value,
            RecordingOutputFieldKey.UPDATED_ON.value,
        ]
