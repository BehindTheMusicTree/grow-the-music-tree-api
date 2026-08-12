from django.urls import include, path
from rest_framework import routers

from grow.view.health import HealthCheckView
from grow.view.viewset.model.album.AlbumViewSet import AlbumViewSet
from grow.view.viewset.model.artist.ArtistViewSet import ArtistViewSet
from grow.view.viewset.model.criteria.children.genre.GenreViewSet import GenreViewSet
from grow.view.viewset.model.criteria.children.tag.TagViewSet import TagViewSet

router = routers.DefaultRouter()

# Do not move PlaylistViewSet after GenrePlaylistViewSet or ManualPlaylistViewSet or it will cause confusion
# resolving reverse urls.
router.register(r"reference/artists", ArtistViewSet, basename="reference-artist")
router.register(r"reference/albums", AlbumViewSet, basename="reference-album")
router.register(r"reference/genres", GenreViewSet, basename="reference-genre")
router.register(r"reference/tags", TagViewSet, basename="reference-tag")

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("", include(router.urls)),
]
