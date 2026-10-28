import io
from types import SimpleNamespace

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


def test_body_is_fully_read_into_a_seekable_file():
    data = bytes(range(256)) * 10

    with spooled_body(SimpleNamespace(_request=_SlowStream(data))) as body:
        assert body.read() == data
        body.seek(0)
        assert body.read(4) == data[:4]


def test_body_over_the_memory_threshold_still_reads_back(monkeypatch):
    monkeypatch.setattr(BulkImportRunMixin, "SPOOL_MEMORY_BYTES", 8)
    data = b"x" * 1000

    with spooled_body(SimpleNamespace(_request=_SlowStream(data))) as body:
        assert body.read() == data
