from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist

from .TagPlaylistManager import TagPlaylistManager


# See CriteriaPlaylist for why this django-stubs relation-resolution ignore is needed.
class TagPlaylist(CriteriaPlaylist):  # type: ignore[django-manager-missing]
    objects: TagPlaylistManager = TagPlaylistManager()

    class Meta:
        db_table = "grow_tag_playlist"
        proxy = True
