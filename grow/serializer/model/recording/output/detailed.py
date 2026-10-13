from django.db.models import Prefetch
from the_music_tree_genre_kit.playlist.Playlist import Playlist

from grow.serializer.model.playlist.base.output.minimum import PlaylistMinimumSerializer

from .RecordingOutputFieldKey import RecordingOutputFieldKey
from .without_playlists import RecordingWithoutPlaylistsSerializer


class RecordingDetailedSerializer(RecordingWithoutPlaylistsSerializer):
    playlists = PlaylistMinimumSerializer(many=True)

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        playlists = PlaylistMinimumSerializer.setup_queryset(Playlist._default_manager.all())
        return (
            super()
            .setup_queryset(queryset, prefix)
            .prefetch_related(Prefetch(f"{prefix}playlists", queryset=playlists))
        )

    class Meta(RecordingWithoutPlaylistsSerializer.Meta):
        fields = [
            *RecordingWithoutPlaylistsSerializer.Meta.fields[:9],
            RecordingOutputFieldKey.PLAYLISTS_PUBLIC.value,
            *RecordingWithoutPlaylistsSerializer.Meta.fields[9:],
        ]
