import io
from types import SimpleNamespace

import pytest
from django.http import UnreadablePostError
from rest_framework.exceptions import ParseError

from grow.view.viewset.mixin import BulkImportRunMixin
from grow.view.viewset.mixin.BulkImportRunMixin import spooled_body


class _SlowStream(io.RawIOBase):
    """Yields at most 3 bytes per read, like a body trickling in from the network."""

    def __init__(self, data: bytes):
        self._data = io.BytesIO(data)

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        chunk = self._data.read(min(3, len(buffer)))
        buffer[: len(chunk)] = chunk
        return len(chunk)


class _DroppedStream(io.RawIOBase):
    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        raise UnreadablePostError("client disconnected")


def _request(stream, content_length: int | None = None):
    meta = {} if content_length is None else {"CONTENT_LENGTH": str(content_length)}
    return SimpleNamespace(_request=stream, META=meta)


def test_body_is_fully_read_into_a_seekable_file():
    data = bytes(range(256)) * 10

    with spooled_body(_request(_SlowStream(data), len(data))) as body:
        assert body.read() == data
        body.seek(0)
        assert body.read(4) == data[:4]


def test_body_over_the_memory_threshold_still_reads_back(monkeypatch):
    monkeypatch.setattr(BulkImportRunMixin, "SPOOL_MEMORY_BYTES", 8)
    data = b"x" * 1000

    with spooled_body(_request(_SlowStream(data))) as body:
        assert body.read() == data


def test_client_disconnecting_mid_upload_is_a_parse_error():
    with pytest.raises(ParseError, match="interrupted"):
        spooled_body(_request(_DroppedStream()))


def test_body_shorter_than_content_length_is_a_parse_error():
    with pytest.raises(ParseError, match="received 10 of 20 bytes"):
        spooled_body(_request(_SlowStream(b"x" * 10), 20))
