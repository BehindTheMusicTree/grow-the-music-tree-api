from rest_framework import serializers

from grow.model.song.Song import Song
from grow.model.song_search.SongSearchManager import GenreFilter
from grow.search.query import SearchQuerySerializer, search_limit
from grow.serializer.model.artist.minimum import ArtistMinimumSerializer
from grow.serializer.model.criteria.output.minimum import CriteriaMinimumSerializer
from grow.serializer.model.song.output.SongOutputFieldKey import SongOutputFieldKey
from grow.serializer.model.song.output.youtube_video import SongYoutubeVideoSerializer

SEARCH_LIMIT_DEFAULT = 8
SEARCH_LIMIT_MAX = 50


class SongSearchQuerySerializer(SearchQuerySerializer):
    limit = search_limit(SEARCH_LIMIT_DEFAULT, SEARCH_LIMIT_MAX)
    genre = serializers.ChoiceField(choices=[f.value for f in GenreFilter], required=False, default=GenreFilter.ANY)
    playable = serializers.BooleanField(required=False, allow_null=True, default=None)


class SongSearchResultSerializer(serializers.ModelSerializer):
    artists = ArtistMinimumSerializer(many=True)
    genre = CriteriaMinimumSerializer(allow_null=True)
    youtube_video = SongYoutubeVideoSerializer(source="*")

    class Meta:
        model = Song
        fields = [
            SongOutputFieldKey.UUID.value,
            SongOutputFieldKey.TITLE.value,
            SongOutputFieldKey.ARTISTS.value,
            SongOutputFieldKey.GENRE.value,
            SongOutputFieldKey.YOUTUBE_VIDEO.value,
            SongOutputFieldKey.FIRST_RELEASE_YEAR.value,
        ]
