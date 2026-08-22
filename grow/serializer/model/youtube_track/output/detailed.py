from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer

from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from grow.serializer.model.album.minimum import AlbumMinimumSerializer
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer
from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer

from .YoutubeTrackOutputFieldKey import YoutubeTrackOutputFieldKey


class YoutubeTrackDetailedSerializer(AppInputSerializer, serializers.ModelSerializer):
    artists = ArtistMinimumSerializer(many=True)
    album = AlbumMinimumSerializer()
    genre = CriteriaMinimumSerializer()
    playlists = PlaylistMinimumSerializer(many=True)

    class Meta:
        model = YoutubeTrack
        fields = [
            YoutubeTrackOutputFieldKey.UUID.value,
            YoutubeTrackOutputFieldKey.RELATIVE_URL.value,
            YoutubeTrackOutputFieldKey.TITLE.value,
            YoutubeTrackOutputFieldKey.ARTISTS.value,
            YoutubeTrackOutputFieldKey.ALBUM.value,
            YoutubeTrackOutputFieldKey.TRACK_NUMBER.value,
            YoutubeTrackOutputFieldKey.GENRE.value,
            YoutubeTrackOutputFieldKey.RATING.value,
            YoutubeTrackOutputFieldKey.LANGUAGE.value,
            YoutubeTrackOutputFieldKey.PLAYLISTS_PUBLIC.value,
            YoutubeTrackOutputFieldKey.PLAY_COUNT.value,
            YoutubeTrackOutputFieldKey.ARCHIVED.value,
            YoutubeTrackOutputFieldKey.YOUTUBE_VIDEO_ID.value,
            YoutubeTrackOutputFieldKey.CREATED_ON.value,
            YoutubeTrackOutputFieldKey.UPDATED_ON.value,
        ]
