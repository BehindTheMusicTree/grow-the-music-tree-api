from enum import StrEnum


class TrackOutputFieldKey(StrEnum):
    CREATED_ON = "created_on"
    UPDATED_ON = "updated_on"
    UUID = "uuid"
    TITLE = "title"
    ARTISTS = "artists"
    ALBUM = "album"
    TRACK_NUMBER = "track_number"
    GENRE = "genre"
    RATING = "rating"
    LANGUAGE = "language"
    PLAYLISTS_PUBLIC = "playlists"
    PLAY_COUNT = "play_count"
    ARCHIVED = "archived"
