from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_genre_kit.track.Track import Track

from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.track.output.TrackOutputFieldKey import TrackOutputFieldKey


class TrackWithoutAlbumPlaylistGenreSerializer(AppInputSerializer, serializers.ModelSerializer):
    artists = ArtistMinimumSerializer(many=True)

    class Meta:
        model = Track
        fields = [
            TrackOutputFieldKey.UUID.value,
            TrackOutputFieldKey.TITLE.value,
            TrackOutputFieldKey.ARTISTS.value,
            TrackOutputFieldKey.RATING.value,
            TrackOutputFieldKey.LANGUAGE.value,
            TrackOutputFieldKey.PLAY_COUNT.value,
        ]
