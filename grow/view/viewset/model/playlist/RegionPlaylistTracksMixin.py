from django.db.models import OuterRef, Subquery
from the_music_tree_genre_kit.view.viewset.playlist.PlaylistTracksActionMixin import PlaylistTracksActionMixin

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
        song = self.get_playlist_song_queryset(playlist).order_by().values("pk")[:1]
        # A scalar lookup keeps counts proportional to playlist membership; an IN/EXISTS semi-join can scan the catalog.
        return (
            super()
            .get_track_playlist_rel_queryset(playlist)
            .alias(_attemptable_song=Subquery(song))
            .filter(_attemptable_song__isnull=False)
        )
