from the_music_tree_genre_kit.playlist.PlaylistManager import PlaylistManager as KitPlaylistManager

from .Fields import Fields


class ManualPlaylistManager(KitPlaylistManager):
    def get_default_ordering(self) -> list[str]:
        return [Fields.NAME_INTERNAL]
