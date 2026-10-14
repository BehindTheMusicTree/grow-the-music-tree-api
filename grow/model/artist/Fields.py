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
    MEMBERS = "members"
    MEMBER_OF = "member_of"
    LINKS = "links"
