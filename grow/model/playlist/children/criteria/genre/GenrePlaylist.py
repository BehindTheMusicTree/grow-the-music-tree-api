from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist

from .GenrePlaylistManager import GenrePlaylistManager


class GenrePlaylist(CriteriaPlaylist):
    objects: GenrePlaylistManager = GenrePlaylistManager()

    class Meta:
        db_table = "grow_genre_playlist"
        proxy = True
