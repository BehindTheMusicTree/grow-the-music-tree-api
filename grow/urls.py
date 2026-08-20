from django.conf import settings
from django.urls import include, path
from rest_framework import routers

from grow.view.health import HealthCheckView
from grow.view.viewset.model.album.AlbumViewSet import AlbumViewSet
from grow.view.viewset.model.artist.ArtistViewSet import ArtistViewSet
from grow.view.viewset.model.criteria.children.genre.GenreViewSet import GenreViewSet
from grow.view.viewset.model.criteria.children.tag.TagViewSet import TagViewSet
from grow.view.viewset.model.play.PlayViewSet import PlayViewSet
from grow.view.viewset.model.playlist.children.criteria.genre.GenrePlaylistViewSet import GenrePlaylistViewSet
from grow.view.viewset.model.playlist.children.criteria.tag.TagPlaylistViewSet import TagPlaylistViewSet
from grow.view.viewset.model.playlist.children.manual.ManualPlaylistViewSet import ManualPlaylistViewSet
from grow.view.viewset.model.playlist.PlaylistViewSet import PlaylistViewSet
from grow.view.viewset.model.youtube_track.YoutubeTrackViewSet import YoutubeTrackViewSet

router = routers.DefaultRouter()

# Do not move PlaylistViewSet after GenrePlaylistViewSet or ManualPlaylistViewSet or it will cause confusion
# resolving reverse urls.
router.register(r"artists", ArtistViewSet, basename="artist")
router.register(r"albums", AlbumViewSet, basename="album")
router.register(r"genres", GenreViewSet, basename="genre")
router.register(r"tags", TagViewSet, basename="tag")
router.register(r"playlists", PlaylistViewSet, basename="playlist")
router.register(r"manual-playlists", ManualPlaylistViewSet, basename="manual-playlist")
router.register(r"genre-playlists", GenrePlaylistViewSet, basename="genre-playlist")
router.register(r"tag-playlists", TagPlaylistViewSet, basename="tag-playlist")
router.register(r"plays", PlayViewSet, basename="play")
router.register(r"library/youtube", YoutubeTrackViewSet, basename="youtube-track")

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path(settings.API_ROOT_BASE, include(router.urls)),
]
