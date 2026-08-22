from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist

from .GenrePlaylistManager import GenrePlaylistManager


# See CriteriaPlaylist for why this django-stubs relation-resolution ignore is needed.
class GenrePlaylist(CriteriaPlaylist):  # type: ignore[django-manager-missing]
    objects: GenrePlaylistManager = GenrePlaylistManager()

    class Meta:
        db_table = "grow_genre_playlist"
        proxy = True
