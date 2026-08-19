from grow.model.trackable_play_count.Fields import Fields as TrackablePlayCountFields


class Fields(TrackablePlayCountFields):
    TITLE = "title"
    ARTISTS = "artists"
    ALBUM = "album"
    TRACK_NUMBER = "track_number"
    GENRE = "genre"
    RATING = "rating"
    LANGUAGE = "language"
    ARCHIVED = "archived"
    PLAYLISTS = "playlists"
    TRACK_PLAYLIST_RELS = "track_playlist_rels"
    UPLOADED_TRACK_RELATED_NAME = "uploadedtrack"
    YOUTUBE_TRACK_RELATED_NAME = "youtubetrack"
