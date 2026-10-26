from enum import StrEnum


class SongOutputFieldKey(StrEnum):
    CREATED_ON = "created_on"
    UPDATED_ON = "updated_on"
    UUID = "uuid"
    RELATIVE_URL = "relative_url"
    TITLE = "title"
    ARTISTS = "artists"
    ALBUM = "album"
    TRACK_NUMBER = "track_number"
    GENRE = "genre"
    RATING = "rating"
    LANGUAGE = "language"
    PLAYLISTS_PUBLIC = "playlists"
    PLAY_COUNT = "play_count"
    YOUTUBE_VIDEO = "youtube_video"
    YOUTUBE_VIDEO_ID = "youtube_video_id"  # legacy, superseded by YOUTUBE_VIDEO
    MUSICBRAINZ_RECORDING_ID = "musicbrainz_recording_id"
    YOUTUBE_UNPLAYABLE_REASON = "youtube_unplayable_reason"  # legacy, superseded by YOUTUBE_VIDEO
