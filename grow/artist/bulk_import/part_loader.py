import json
import uuid
from typing import IO, Any

from django.conf import settings
from rest_framework.exceptions import ValidationError

from grow.artist.bulk_import.ArtistImportStaging import ArtistImportStaging
from grow.bulk_import.copy_part import copy_part
from grow.model.artist.Artist import Artist
from grow.model.artist_link.ArtistLink import ArtistLink

TYPES = set(Artist.Type.values)
LINK_KINDS = set(ArtistLink.Kind.values)
# A btree key (artist, kind, url) must stay under ~2.7 kB.
LINK_URL_LEN_MAX = 2048  # bytes
# Same btree key limit for the unique (artist, name) alias index.
ALIAS_NAME_LEN_MAX = 2048  # bytes
IMAGE_URL_LEN_MAX = 2048  # bytes


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


def _is_https_url(value: Any) -> bool:
    return _is_text(value) and value.startswith("https://") and len(value.encode()) <= IMAGE_URL_LEN_MAX


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
        _require(isinstance(image, dict), line_number, "image must be an object")
        for key in ("url", "page_url"):
            _require(
                _is_https_url(image.get(key)),
                line_number,
                f"image {key} must be an https URL of at most {IMAGE_URL_LEN_MAX} bytes",
            )
        _require(_is_text(image.get("license")), line_number, "image license must be a non-empty string")
        author = image.get("author")
        _require(author is None or _is_text(author), line_number, "image author must be a non-empty string")
        # Commons serves some license URLs as plain http, so only the scheme is checked: the frontend links it.
        license_url = image.get("license_url")
        _require(
            license_url is None
            or (
                _is_text(license_url)
                and license_url.startswith(("http://", "https://"))
                and len(license_url.encode()) <= IMAGE_URL_LEN_MAX
            ),
            line_number,
            f"image license_url must be an http(s) URL of at most {IMAGE_URL_LEN_MAX} bytes",
        )
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
            _is_text(link.get("url")) and len(link["url"].encode()) <= LINK_URL_LEN_MAX,
            line_number,
            f"link url must be a non-empty string of at most {LINK_URL_LEN_MAX} bytes",
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
