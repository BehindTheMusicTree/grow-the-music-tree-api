import json
import re
import uuid
from typing import IO, Any

from django.conf import settings
from rest_framework.exceptions import ValidationError
from the_music_tree_api_kit.commons_image.validation import validate_commons_image

from grow.artist.bulk_import.ArtistImportStaging import ArtistImportStaging
from grow.bulk_import.copy_part import copy_part
from grow.model.artist.Artist import Artist
from grow.model.artist_link.ArtistLink import ArtistLink

TYPES = set(Artist.Type.values)
ORIGIN_SOURCES = set(Artist.OriginSource.values)
WIKIDATA_ID = re.compile(r"Q[1-9][0-9]*")
LINK_KINDS = set(ArtistLink.Kind.values)
# A btree key (artist, kind, url) must stay under ~2.7 kB.
LINK_URL_LEN_MAX = 2048  # bytes
# Same btree key limit for the unique (artist, name) alias index.
ALIAS_NAME_LEN_MAX = 2048  # bytes


def _require(condition: bool, line_number: int, message: str) -> None:
    if not condition:
        raise ValidationError(f"line {line_number}: {message}")


def _is_mbid(value: Any) -> bool:
    try:
        uuid.UUID(value)
    except ValueError, TypeError, AttributeError:
        return False
    return True


def _is_text(value: Any, max_length: int | None = None) -> bool:
    return isinstance(value, str) and value != "" and (max_length is None or len(value) <= max_length)


def _is_year(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and -32768 <= value <= 32767)


def _is_text_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_text(item) for item in value)


def _is_number_in(value: Any, low: float, high: float) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and low <= value <= high


def _validate_origin(line_number: int, origin: Any) -> None:
    _require(isinstance(origin, dict), line_number, "origin must be an object")
    _require(_is_text(origin.get("name")), line_number, "origin name must be a non-empty string")
    kind = origin.get("kind")
    _require(kind is None or _is_text(kind), line_number, "origin kind must be null or a non-empty string")
    _require(origin.get("source") in ORIGIN_SOURCES, line_number, "unknown origin source")
    wikidata_id = origin.get("wikidata_id")
    _require(
        wikidata_id is None or (isinstance(wikidata_id, str) and WIKIDATA_ID.fullmatch(wikidata_id) is not None),
        line_number,
        "origin wikidata_id must be a QID",
    )
    longitude, latitude = origin.get("longitude"), origin.get("latitude")
    _require(
        (longitude is None) == (latitude is None)
        and (longitude is None or (_is_number_in(longitude, -180, 180) and _is_number_in(latitude, -90, 90))),
        line_number,
        "origin longitude and latitude must be set together and in range",
    )
    region_id = origin.get("region_id")
    _require(
        region_id is None or _is_text(region_id, 64), line_number, "origin region_id must be a string of at most 64"
    )


def _row(line_number: int, line: bytes) -> tuple:
    try:
        artist = json.loads(line)
    except ValueError as e:
        raise ValidationError(f"line {line_number}: invalid artist ({e})") from e
    _require(isinstance(artist, dict), line_number, "artist must be an object")
    _require(_is_mbid(artist.get("musicbrainz_artist_id")), line_number, "musicbrainz_artist_id must be a UUID")
    _require(
        _is_text(artist.get("name"), settings.ARTIST_NAME_LEN_MAX),
        line_number,
        f"name must be a non-empty string of at most {settings.ARTIST_NAME_LEN_MAX} characters",
    )
    _require(artist.get("type") in TYPES | {None}, line_number, "unknown type")
    country = artist.get("country")
    _require(country is None or (_is_text(country) and len(country) == 2), line_number, "country must be ISO 3166-1")
    _require(_is_year(artist.get("begin_year")) and _is_year(artist.get("end_year")), line_number, "invalid year")
    _require(isinstance(artist.get("ended"), bool), line_number, "ended must be a boolean")
    disambiguation = artist.get("disambiguation")
    _require(
        disambiguation is None or _is_text(disambiguation, settings.ARTIST_NAME_LEN_MAX),
        line_number,
        f"disambiguation must be a non-empty string of at most {settings.ARTIST_NAME_LEN_MAX} characters",
    )
    aliases = artist.get("aliases", [])
    _require(
        _is_text_list(aliases) and all(len(alias.encode()) <= ALIAS_NAME_LEN_MAX for alias in aliases),
        line_number,
        f"aliases must be a list of non-empty strings of at most {ALIAS_NAME_LEN_MAX} bytes",
    )
    # Parts exported before images existed have no `image` key: it stages as null.
    image = artist.get("image")
    if image is not None:
        image_error = validate_commons_image(image)
        _require(image_error is None, line_number, str(image_error))
    # Parts exported before origins existed have no `origin` key: it stages as null.
    origin = artist.get("origin")
    if origin is not None:
        _validate_origin(line_number, origin)
    for key in ("members", "links", "release_groups"):
        _require(
            isinstance(artist.get(key), list) and all(isinstance(item, dict) for item in artist[key]),
            line_number,
            f"{key} must be a list of objects",
        )
    for member in artist["members"]:
        _require(_is_mbid(member.get("musicbrainz_artist_id")), line_number, "member MBID must be a UUID")
        _require(_is_year(member.get("begin_year")) and _is_year(member.get("end_year")), line_number, "invalid year")
        _require(isinstance(member.get("ended"), bool), line_number, "member ended must be a boolean")
        _require(_is_text_list(member.get("roles")), line_number, "member roles must be a list of strings")
    for link in artist["links"]:
        _require(link.get("kind") in LINK_KINDS, line_number, "unknown link kind")
        _require(
            _is_text(link.get("url"))
            and link["url"].startswith(("http://", "https://"))
            and len(link["url"].encode()) <= LINK_URL_LEN_MAX,
            line_number,
            f"link url must be an http(s) URL of at most {LINK_URL_LEN_MAX} bytes",
        )
    for release_group in artist["release_groups"]:
        _require(_is_mbid(release_group.get("musicbrainz_release_group_id")), line_number, "release group MBID invalid")
        _require(
            _is_text(release_group.get("title"), settings.ALBUM_NAME_LEN_MAX),
            line_number,
            f"release group title must be a non-empty string of at most {settings.ALBUM_NAME_LEN_MAX} characters",
        )
        primary_type = release_group.get("primary_type")
        _require(primary_type is None or _is_text(primary_type), line_number, "invalid release group primary_type")
        _require(_is_text_list(release_group.get("secondary_types")), line_number, "invalid secondary_types")
        year = release_group.get("first_release_year")
        # Four digits, so the text `Album.year` sorts chronologically.
        _require(year is None or (_is_year(year) and 1000 <= year <= 9999), line_number, "invalid first_release_year")
    return artist["musicbrainz_artist_id"], json.dumps(artist)


def load_part(run_id: int, part: int, body: IO[bytes]) -> int:
    return copy_part(ArtistImportStaging, ("musicbrainz_artist_id", "data"), _row, run_id, part, body)
