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
from grow.view.viewset.model.uploaded_track.UploadedTrackViewSet import UploadedTrackViewSet

router = routers.DefaultRouter()

# Do not move PlaylistViewSet after GenrePlaylistViewSet or ManualPlaylistViewSet or it will cause confusion
# resolving reverse urls.
router.register(r"reference/artists", ArtistViewSet, basename="reference-artist")
router.register(r"reference/albums", AlbumViewSet, basename="reference-album")
router.register(r"reference/genres", GenreViewSet, basename="reference-genre")
router.register(r"reference/tags", TagViewSet, basename="reference-tag")
router.register(r"reference/playlists", PlaylistViewSet, basename="reference-playlist")
router.register(r"reference/manual-playlists", ManualPlaylistViewSet, basename="reference-manual-playlist")
router.register(r"reference/genre-playlists", GenrePlaylistViewSet, basename="reference-genre-playlist")
router.register(r"reference/tag-playlists", TagPlaylistViewSet, basename="reference-tag-playlist")
router.register(r"reference/plays", PlayViewSet, basename="reference-play")
router.register(r"reference/library/uploaded", UploadedTrackViewSet, basename="reference-uploaded-track")

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("v0/", include(router.urls)),
]
