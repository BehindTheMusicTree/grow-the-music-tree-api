from django.db.models import Exists, OuterRef
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from the_music_tree_genre_kit.view.viewset.playlist.PlaylistTracksActionMixin import (
    FROM_QUERY_PARAM,
    PlaylistTracksActionMixin,
)

from grow.genre_graph.snapshot import graph_snapshot
from grow.model.song.playable import RESTRICTED_POLICY
from grow.model.song.Song import Song
from grow.serializer.model.track_playlist_rel.output.in_page import TrackPlaylistRelInPageSerializer
from grow.youtube_regions import attemptable, viewer_country, with_region_status


def blocked_restricted_songs(country):
    """Songs whose policy blocks `country`; the restricted predicate lets PostgreSQL use the partial index."""
    return with_region_status(Song.objects.all(), country).filter(RESTRICTED_POLICY, _region_blocked=True)


TRACKS_DESCRIPTION = (
    "The playlist's track relations in play order (position ascending, unpositioned last). `?from=<track uuid>` starts"
    " the list at that track's relation (inclusive); 404 if the track is not in the playlist, 400 if the value is not a"
    " UUID."
)
FROM_TRACK_PARAMETER = OpenApiParameter(
    FROM_QUERY_PARAM, OpenApiTypes.UUID, required=False, description="Start the list at this track (inclusive)."
)


# Applied by each viewset (a mixin has no `schema` for `extend_schema_view`). The action lists the playlist's members
# without `filter_queryset`: the viewset's filterset does not apply.
TRACKS_SCHEMA = extend_schema_view(
    tracks=extend_schema(
        description=TRACKS_DESCRIPTION,
        parameters=[FROM_TRACK_PARAMETER],
        responses=TrackPlaylistRelInPageSerializer(many=True),
        filters=False,
    )
)


class RegionPlaylistTracksMixin(PlaylistTracksActionMixin):
    tracks = graph_snapshot(PlaylistTracksActionMixin.tracks)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if self.action == "tracks":
            response["Cache-Control"] = "private, no-store"
            response["X-Playback-Country"] = viewer_country(request) or "unknown"
        return response

    def get_playlist_song_queryset(self, playlist):
        country = viewer_country(self.request)
        return with_region_status(Song.objects.filter(pk=OuterRef("track_id")), country).filter(attemptable(country))

    def get_track_playlist_rel_queryset(self, playlist):
        # Genre playlists hold only playable songs (every writer maintains that), so only the region policy can hide a
        # member. A top-level anti-join over the restricted partial index costs the number of restricted songs, not
        # the catalogue; keep it out of any OR, where PostgreSQL may hash the subplan and scan the whole table.
        blocked = blocked_restricted_songs(viewer_country(self.request)).filter(pk=OuterRef("track_id"))
        return super().get_track_playlist_rel_queryset(playlist).filter(~Exists(blocked))
