from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin

from grow.model.song.Song import Song
from grow.serializer.model.album.minimum import AlbumMinimumSerializer
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer

from .SongOutputFieldKey import SongOutputFieldKey
from .youtube_video import SongYoutubeVideoSerializer


class SongWithoutPlaylistsSerializer(EagerLoadingMixin, AppInputSerializer, serializers.ModelSerializer):
    artists = ArtistMinimumSerializer(many=True)
    album = AlbumMinimumSerializer()
    genre = CriteriaMinimumSerializer()
    youtube_video = SongYoutubeVideoSerializer(source="*")

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        return queryset.select_related(f"{prefix}album", f"{prefix}genre").prefetch_related(f"{prefix}artists")

    class Meta:
        model = Song
        fields = [
            SongOutputFieldKey.UUID.value,
            SongOutputFieldKey.RELATIVE_URL.value,
            SongOutputFieldKey.TITLE.value,
            SongOutputFieldKey.ARTISTS.value,
            SongOutputFieldKey.ALBUM.value,
            SongOutputFieldKey.TRACK_NUMBER.value,
            SongOutputFieldKey.GENRE.value,
            SongOutputFieldKey.RATING.value,
            SongOutputFieldKey.LANGUAGE.value,
            SongOutputFieldKey.PLAY_COUNT.value,
            SongOutputFieldKey.YOUTUBE_VIDEO.value,
            # Legacy flat YouTube fields, removed once consumers read youtube_video.
            SongOutputFieldKey.YOUTUBE_VIDEO_ID.value,
            SongOutputFieldKey.MUSICBRAINZ_RECORDING_ID.value,
            SongOutputFieldKey.YOUTUBE_UNPLAYABLE_REASON.value,
            SongOutputFieldKey.CREATED_ON.value,
            SongOutputFieldKey.UPDATED_ON.value,
        ]
