from rest_framework import serializers


class GenreScopedCountsSerializer(serializers.Serializer):
    genre_only_tracks_count = serializers.IntegerField()
    genre_and_subgenres_tracks_count = serializers.DictField(child=serializers.IntegerField())


class ArtistGenreCountSerializer(GenreScopedCountsSerializer):
    genre_playlist = serializers.UUIDField()
    songs_count = serializers.IntegerField(help_text="The artist's catalogue songs in the genre and its subgenres.")
    tracks_count = serializers.IntegerField(help_text="The artist's tracks in the genre playlist.")
    catalogue = GenreScopedCountsSerializer()
