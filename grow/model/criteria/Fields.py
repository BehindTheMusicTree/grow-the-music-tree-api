from the_music_tree_genre_kit.criteria.Fields import Fields as AbstractCriteriaFields

from grow.model.uploaded_track_mixin.Fields import Fields as UploadedTrackMixinFields


class Fields(UploadedTrackMixinFields, AbstractCriteriaFields):
    UPLOADED_TRACKS_RELATED_NAME = "uploaded_tracks_of_criteria"
    CRITERIA_PLAYLIST = "criteria_playlist"
    TREE = "tree"
