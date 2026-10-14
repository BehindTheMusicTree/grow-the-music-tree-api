from grow.model.album.Fields import Fields as AlbumFields
from grow.model.artist.Fields import Fields as ArtistFields


class Fields:
    CREATED_ON = ArtistFields.CREATED_ON
    UPDATED_ON = ArtistFields.UPDATED_ON
    UUID = ArtistFields.UUID
    NAME_PUBLIC = ArtistFields.NAME_PUBLIC
    ALBUMS = ArtistFields.ALBUMS
    ALBUM_ARTISTS = AlbumFields.ALBUM_ARTISTS
    TRACKS_RELATED_NAME = ArtistFields.TRACKS_RELATED_NAME
    TRACKS_COUNT_PUBLIC = ArtistFields.TRACKS_COUNT_PUBLIC
    # The model's `tracks_count` property runs one query per artist, so serializers read this annotation instead.
    TRACKS_COUNT_ANNOTATED = "tracks_count_annotated"
    MUSICBRAINZ_ARTIST_ID = ArtistFields.MUSICBRAINZ_ARTIST_ID
    TYPE = ArtistFields.TYPE
    COUNTRY = ArtistFields.COUNTRY
    BEGIN_YEAR = ArtistFields.BEGIN_YEAR
    END_YEAR = ArtistFields.END_YEAR
    ENDED = ArtistFields.ENDED
    LINKS = ArtistFields.LINKS
    MEMBERS = ArtistFields.MEMBERS
    MEMBER_OF = ArtistFields.MEMBER_OF
