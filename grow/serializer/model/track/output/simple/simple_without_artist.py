from rest_framework import serializers

from grow.model.track.Track import Track
from grow.serializer.model.album.minimum import AlbumMinimumSerializer
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer
from grow.serializer.model.track.output.TrackOutputFieldKey import TrackOutputFieldKey


class TrackSimpleWithoutPlaylistAndArtistSerializer(serializers.ModelSerializer):
    album = AlbumMinimumSerializer()
    genre = CriteriaMinimumSerializer()

    class Meta:
        model = Track
        fields = [
            TrackOutputFieldKey.UUID.value,
            TrackOutputFieldKey.TITLE.value,
            TrackOutputFieldKey.ALBUM.value,
            TrackOutputFieldKey.GENRE.value,
            TrackOutputFieldKey.RATING.value,
            TrackOutputFieldKey.LANGUAGE.value,
            TrackOutputFieldKey.PLAY_COUNT.value,
        ]
