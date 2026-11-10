from django.db.models import Exists, OuterRef, Q
from the_music_tree_genre_kit.view.viewset.playlist.PlaylistTracksActionMixin import PlaylistTracksActionMixin

from grow.model.song.playable import OPEN_PLAYABLE
from grow.model.song.Song import Song
from grow.youtube_regions import attemptable, viewer_country, with_region_status


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
        country = viewer_country(self.request)
        # Scalar lookups keep counts proportional to playlist membership; an IN/EXISTS semi-join can scan the catalog.
        # Most songs are playable under any policy: that probe is answered by the partial index alone, and only the
        # remainder (regional policies, unknown metadata) is read from the heap. Inside an OR the two probes stay
        # per-row subplans, the second evaluated only when the first fails.
        open_song = Song.objects.filter(pk=OuterRef("track_id")).filter(OPEN_PLAYABLE)
        regional_song = with_region_status(Song.objects.filter(pk=OuterRef("track_id")), country).filter(
            attemptable(country)
        )
        return (
            super()
            .get_track_playlist_rel_queryset(playlist)
            .alias(_open_playable=Exists(open_song), _attemptable=Exists(regional_song))
            .filter(Q(_open_playable=True) | Q(_attemptable=True))
        )
