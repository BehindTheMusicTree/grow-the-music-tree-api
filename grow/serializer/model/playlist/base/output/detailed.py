from rest_framework import serializers
from the_music_tree_api_kit.serializer.field.AppCharField import AppCharField
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.serializer.model.track_playlist_rel.output.without_playlist import TrackPlaylistRelWithoutPlaylist

from .Fields import Fields


class PlaylistDetailedSerializer(serializers.ModelSerializer):
    track_playlist_relations = TrackPlaylistRelWithoutPlaylist(source=Fields.TRACK_PLAYLIST_RELS_INTERNAL, many=True)
    tracks_count = serializers.IntegerField()
    type = AppCharField(source=Fields.TYPE_LABEL_INTERNAL)

    class Meta:
        model = Playlist
        fields = [
            Fields.UUID,
            Fields.NAME,
            Fields.TYPE_LABEL_PUBLIC,
            Fields.TRACKS_COUNT_PUBLIC,
            Fields.TRACK_PLAYLIST_RELS_PUBLIC,
            Fields.PLAY_COUNT,
            Fields.CREATED_ON,
            Fields.UPDATED_ON,
        ]
