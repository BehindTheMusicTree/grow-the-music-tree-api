from the_music_tree_genre_kit.criteria.Fields import Fields as AbstractCriteriaFields
from the_music_tree_genre_kit.track_mixin.Fields import Fields as TrackMixinFields


class Fields(TrackMixinFields, AbstractCriteriaFields):
    TRACKS_RELATED_NAME = "tracks_of_criteria"
    CRITERIA_PLAYLIST = "criteria_playlist"
    TREE = "tree"
