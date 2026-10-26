from django.db.models import Prefetch
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer

from .SongOutputFieldKey import SongOutputFieldKey
from .without_playlists import SongWithoutPlaylistsSerializer


class SongDetailedSerializer(SongWithoutPlaylistsSerializer):
    playlists = PlaylistMinimumSerializer(many=True)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        playlists = PlaylistMinimumSerializer.setup_queryset(Playlist._default_manager.all())
        return (
            super()
            .setup_queryset(queryset, prefix)
            .prefetch_related(Prefetch(f"{prefix}playlists", queryset=playlists))
        )

    class Meta(SongWithoutPlaylistsSerializer.Meta):
        fields = [
            *SongWithoutPlaylistsSerializer.Meta.fields[:9],
            SongOutputFieldKey.PLAYLISTS_PUBLIC.value,
            *SongWithoutPlaylistsSerializer.Meta.fields[9:],
        ]
