from enum import StrEnum


class CriteriaOutputFieldKey(StrEnum):
    CREATED_ON = "created_on"
    UPDATED_ON = "updated_on"
    UUID = "uuid"
    NAME = "name"
    NAME_INTERNAL = "_name"
    TRACKS_NOT_ARCHIVED_INTERNAL = "tracks_not_archived"
    TRACKS_NOT_ARCHIVED_PUBLIC = "tracks"
    TRACKS_NOT_ARCHIVED_COUNT_INTERNAL = "tracks_not_archived_count"
    TRACKS_NOT_ARCHIVED_COUNT_PUBLIC = "tracks_count"
    TRACKS_ARCHIVED_COUNT_INTERNAL = "tracks_archived_count"
    TRACKS_ARCHIVED_COUNT_PUBLIC = "tracks_archived_count"
    ROOT = "root"
    PARENT = "parent"
    ASCENDANTS = "ascendants"
    DESCENDANTS = "descendants"
    CHILDREN = "children"
    CRITERIA_PLAYLIST = "criteria_playlist"
    SIDE = "side"
    ESSENTIAL_TRACKS = "essential_tracks"
