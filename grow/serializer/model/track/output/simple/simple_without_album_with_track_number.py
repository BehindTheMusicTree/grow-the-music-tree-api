from rest_framework import serializers
from the_music_tree_genre_kit.track.Track import Track

from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer

from ..TrackOutputFieldKey import TrackOutputFieldKey


class TrackSimpleWithoutAlbumWithPositionInAlbumSerializer(serializers.ModelSerializer):
    genre = CriteriaMinimumSerializer()
    artists = ArtistMinimumSerializer(many=True)

    class Meta:
        model = Track
        fields = [
            TrackOutputFieldKey.UUID.value,
            TrackOutputFieldKey.TITLE.value,
            TrackOutputFieldKey.ARTISTS.value,
            TrackOutputFieldKey.TRACK_NUMBER.value,
            TrackOutputFieldKey.GENRE.value,
            TrackOutputFieldKey.RATING.value,
            TrackOutputFieldKey.LANGUAGE.value,
            TrackOutputFieldKey.PLAY_COUNT.value,
        ]
