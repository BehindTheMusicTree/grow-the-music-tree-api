"""The single opaque cursor of `library/songs/`: the last row of a page, in one ordering."""

import base64
import binascii
import json
from dataclasses import dataclass
from uuid import UUID

from rest_framework.exceptions import ParseError

CURSOR_VERSION = 1
PK_ORDERING = ""  # no `ordering` param: pk order


@dataclass(frozen=True)
class SongCursor:
    ordering: str
    key: str | int | None  # the last row's sort key; None for PK_ORDERING or a year-less song
    song_id: UUID

    def encode(self) -> str:
        payload = [CURSOR_VERSION, self.ordering, self.key, str(self.song_id)]
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    @classmethod
    def decode(cls, raw: str, ordering: str) -> SongCursor:
        try:
            text = base64.urlsafe_b64decode(raw.encode()).decode()
            cursor = cls._parse(text, ordering)
        except (ValueError, TypeError, AttributeError, binascii.Error, UnicodeDecodeError) as error:
            raise ParseError("Invalid cursor.") from error
        if cursor.ordering != ordering:
            raise ParseError("Cursor does not match `ordering`.")
        if not _valid_key(cursor.key, ordering):
            raise ParseError("Invalid cursor.")
        return cursor

    @classmethod
    def _parse(cls, text: str, ordering: str) -> SongCursor:
        # Legacy cursors (bare uuid for genre panels, [key, id] for artists), so a scroll in progress survives the
        # deploy: drop once released clients have re-fetched.
        if not text.startswith("["):
            return cls(PK_ORDERING, None, UUID(text))
        payload = json.loads(text)
        if len(payload) == 2 and ordering != PK_ORDERING:
            key, song_id = payload
            return cls(ordering, key, UUID(song_id))
        version, cursor_ordering, key, song_id = payload
        if version != CURSOR_VERSION:
            raise ValueError(f"Unknown cursor version {version!r}.")
        return cls(cursor_ordering, key, UUID(song_id))


def _valid_key(key: object, ordering: str) -> bool:
    if ordering == PK_ORDERING:
        return key is None
    if ordering.lstrip("-") == "title":
        return isinstance(key, str) and "\x00" not in key
    return key is None or type(key) is int
