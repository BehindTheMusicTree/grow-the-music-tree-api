from typing import Any

from the_music_tree_genre_kit.criteria.playlist.AbstractCriteriaPlaylistManager import AbstractCriteriaPlaylistManager
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks


class CriteriaPlaylistManager(AbstractCriteriaPlaylistManager):
    def ensure_criterialess(self, user: Any) -> None:
        """
        Creates the user's Genreless and Tagless playlists when missing. A freshly emptied catalogue has none, and
        the song import files genreless songs in the Genreless one. Idempotent.
        """
        for type_pk in (CriteriaTypePks.GENRE, CriteriaTypePks.TAG):
            self.get_or_create(user=user, criteria=None, type_id=type_pk.value)
