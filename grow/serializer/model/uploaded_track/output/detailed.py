from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer

from grow.model.uploaded_track.UploadedTrack import UploadedTrack
from grow.serializer.model.album.minimum import AlbumMinimumSerializer
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer
from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer

from .UploadedTrackOutputFieldKey import UploadedTrackOutputFieldKey


class UploadedTrackDetailedSerializer(AppInputSerializer, serializers.ModelSerializer):
    artists = ArtistMinimumSerializer(many=True)
    album = AlbumMinimumSerializer()
    genre = CriteriaMinimumSerializer()
    playlists = PlaylistMinimumSerializer(many=True)

    class Meta:
        model = UploadedTrack
        fields = [
            UploadedTrackOutputFieldKey.UUID.value,
            UploadedTrackOutputFieldKey.RELATIVE_URL.value,
            UploadedTrackOutputFieldKey.TITLE.value,
            UploadedTrackOutputFieldKey.ARTISTS.value,
            UploadedTrackOutputFieldKey.ALBUM.value,
            UploadedTrackOutputFieldKey.TRACK_NUMBER.value,
            UploadedTrackOutputFieldKey.GENRE.value,
            UploadedTrackOutputFieldKey.RATING.value,
            UploadedTrackOutputFieldKey.LANGUAGE.value,
            UploadedTrackOutputFieldKey.PLAYLISTS_PUBLIC.value,
            UploadedTrackOutputFieldKey.PLAY_COUNT.value,
            UploadedTrackOutputFieldKey.ARCHIVED.value,
            UploadedTrackOutputFieldKey.CREATED_ON.value,
            UploadedTrackOutputFieldKey.UPDATED_ON.value,
        ]
