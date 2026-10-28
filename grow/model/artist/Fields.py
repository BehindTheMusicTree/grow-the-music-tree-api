from the_music_tree_genre_kit.track_mixin.Fields import Fields as TrackMixinFields


class Fields(TrackMixinFields):
    TRACKS_RELATED_NAME = "tracks_of_artist"
    ALBUMS = "albums"
    MUSICBRAINZ_ARTIST_ID = "musicbrainz_artist_id"
    TYPE = "type"
    COUNTRY = "country"
    BEGIN_YEAR = "begin_year"
    END_YEAR = "end_year"
    ENDED = "ended"
    DISAMBIGUATION = "disambiguation"
    RECORDING_COUNT = "recording_count"
    IMAGE_URL = "image_url"
    IMAGE_PAGE_URL = "image_page_url"
    IMAGE_AUTHOR = "image_author"
    IMAGE_LICENSE = "image_license"
    IMAGE_LICENSE_URL = "image_license_url"
    MEMBERS = "members"
    MEMBER_OF = "member_of"
    LINKS = "links"
    ALIASES = "aliases"
    IS_SPECIAL_PURPOSE = "is_special_purpose"
