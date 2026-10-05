from django.conf import settings
from django.urls import include, path
from rest_framework import routers

from grow.view.auth_me import AuthMeView
from grow.view.curation import (
    CurationEntriesView,
    CurationEntryView,
    CurationExportView,
    CurationHistoryView,
    CurationListsView,
    CurationRulesView,
    CurationStatusView,
)
from grow.view.health import HealthCheckView
from grow.view.import_run import ImportRunLatestView, ImportRunListView, ImportRunUnresolvedGenreTagsView
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

urlpatterns = [path("health/", HealthCheckView.as_view(), name="health")]

urlpatterns += [
    path(f"{settings.API_ROOT_BASE}auth/me/", AuthMeView.as_view(), name="auth-me"),
    path(f"{settings.API_ROOT_BASE}curation/lists/", CurationListsView.as_view(), name="curation-lists"),
    path(f"{settings.API_ROOT_BASE}curation/history/", CurationHistoryView.as_view(), name="curation-history"),
    path(f"{settings.API_ROOT_BASE}curation/status/", CurationStatusView.as_view(), name="curation-status"),
    path(f"{settings.API_ROOT_BASE}curation/rules/", CurationRulesView.as_view(), name="curation-rules"),
    path(f"{settings.API_ROOT_BASE}curation/export/", CurationExportView.as_view(), name="curation-export"),
    path(
        f"{settings.API_ROOT_BASE}curation/<str:list_name>/entries/",
        CurationEntriesView.as_view(),
        name="curation-entries",
    ),
    path(
        f"{settings.API_ROOT_BASE}curation/<str:list_name>/entries/<uuid:uuid>/",
        CurationEntryView.as_view(),
        name="curation-entry",
    ),
    path(f"{settings.API_ROOT_BASE}pipeline/imports/", ImportRunListView.as_view(), name="import-runs"),
    path(f"{settings.API_ROOT_BASE}pipeline/imports/latest/", ImportRunLatestView.as_view(), name="import-runs-latest"),
    path(
        f"{settings.API_ROOT_BASE}pipeline/imports/unresolved-genre-tags/",
        ImportRunUnresolvedGenreTagsView.as_view(),
        name="import-runs-unresolved-genre-tags",
    ),
    path(settings.API_ROOT_BASE, include(router.urls)),
]
