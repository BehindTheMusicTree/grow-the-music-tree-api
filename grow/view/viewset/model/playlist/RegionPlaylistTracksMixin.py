from django.db.models import Exists, OuterRef
from the_music_tree_genre_kit.view.viewset.playlist.PlaylistTracksActionMixin import PlaylistTracksActionMixin

from grow.model.song.playable import RESTRICTED_POLICY
from grow.model.song.Song import Song
from grow.youtube_regions import attemptable, viewer_country, with_region_status


def blocked_restricted_songs(country):
    """Songs whose policy blocks `country`; the restricted predicate lets PostgreSQL use the partial index."""
    return with_region_status(Song.objects.all(), country).filter(RESTRICTED_POLICY, _region_blocked=True)


class RegionPlaylistTracksMixin(PlaylistTracksActionMixin):
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
