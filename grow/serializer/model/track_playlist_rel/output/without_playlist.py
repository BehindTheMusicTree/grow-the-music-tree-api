from django.db.models import Prefetch
from rest_framework import serializers
from the_music_tree_api_kit.serializer.AppInputSerializer import AppInputSerializer
from the_music_tree_api_kit.serializer.EagerLoadingMixin import EagerLoadingMixin
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.serializer.model.youtube_track.output.detailed import YoutubeTrackDetailedSerializer

from .Fields import Fields


class TrackPlaylistRelWithoutPlaylist(EagerLoadingMixin, AppInputSerializer, serializers.ModelSerializer):
    track = YoutubeTrackDetailedSerializer(source=f"{Fields.TRACK_INTERNAL}.youtubetrack")

    @classmethod
    def setup_queryset(cls, queryset, prefix=""):
        youtube_track = f"{prefix}track__youtubetrack"
        return YoutubeTrackDetailedSerializer.setup_queryset(
            queryset.select_related(youtube_track), prefix=f"{youtube_track}__"
        )

    @classmethod
    def prefetch(cls, queryset, lookup):
        """Prefetches the rels behind `lookup`, loaded the way this serializer reads them."""
        return queryset.prefetch_related(
            Prefetch(lookup, queryset=cls.setup_queryset(TrackPlaylistRel._default_manager.all()))
        )

    class Meta:
        model = TrackPlaylistRel
        fields = [
            Fields.TRACK_PUBLIC,
            Fields.POSITION,
        ]
