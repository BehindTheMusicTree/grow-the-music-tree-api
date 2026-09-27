from django.db.models import Prefetch
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer

from .without_playlists import YoutubeTrackWithoutPlaylistsSerializer
from .YoutubeTrackOutputFieldKey import YoutubeTrackOutputFieldKey


class YoutubeTrackDetailedSerializer(YoutubeTrackWithoutPlaylistsSerializer):
    playlists = PlaylistMinimumSerializer(many=True)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        playlists = PlaylistMinimumSerializer.setup_queryset(Playlist._default_manager.all())
        return (
            super()
            .setup_queryset(queryset, prefix)
            .prefetch_related(Prefetch(f"{prefix}playlists", queryset=playlists))
        )

    class Meta(YoutubeTrackWithoutPlaylistsSerializer.Meta):
        fields = [
            *YoutubeTrackWithoutPlaylistsSerializer.Meta.fields[:9],
            YoutubeTrackOutputFieldKey.PLAYLISTS_PUBLIC.value,
            *YoutubeTrackWithoutPlaylistsSerializer.Meta.fields[9:],
        ]
