"""Measure approved HTTP reads from trusted code outside candidate processes.

The caller supplies an isolated numeric endpoint observed from the private
runtime, and keeps admission, health supervision and the deadline throughout.
Definitions contain data only; no candidate code is imported by this runner.
"""

import hashlib
import http.client
import ipaddress
import json
import os
import socket
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .manifest import exact_keys, matching, positive_integer, trusted_json
from .scenario_plan import canonical_bytes

MAX_RESPONSE_BYTES = 4 * 1024**2


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: Path, timeout: int):
        super().__init__("grow-perf.invalid", timeout=timeout)
        if not path.is_absolute() or len(str(path).encode()) > 103:
            raise ValueError("absolute, bounded Unix HTTP socket path required")
        self.path = path

    def connect(self) -> None:
        if not hasattr(os, "O_PATH"):
            raise RuntimeError("Unix HTTP measurement requires Linux O_PATH")
        descriptor = os.open(self.path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if not stat.S_ISSOCK(os.fstat(descriptor).st_mode):
                raise ValueError("Unix HTTP endpoint must be a socket, without symlinks")
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            # The candidate owns the socket directory. Pin its inode before
            # connecting so a concurrent replacement cannot redirect root HTTP.
            self.sock.connect(f"/proc/self/fd/{descriptor}")
        except BaseException:
            self.close()
            raise
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class HTTPScenario:
    path: str
    status: int
    response_sha256: str
    warmups: int
    timeout_seconds: int

    @classmethod
    def parse(cls, raw: object) -> HTTPScenario:
        value = exact_keys(raw, {"version", "path", "status", "response_sha256", "warmups", "timeout_seconds"})
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("unsupported HTTP scenario version")
        path = value["path"]
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or len(path) > 4096
            or any(ord(character) < 33 or ord(character) > 126 for character in path)
            or "#" in path
        ):
            raise ValueError("scenario requires an ASCII origin-relative request path")
        return cls(
            path,
            positive_integer(value["status"], "expected HTTP success status", 200, 299),
            matching(value["response_sha256"], r"[0-9a-f]{64}", "expected canonical JSON response digest"),
            positive_integer(value["warmups"], "warmup count", 1, 100),
            positive_integer(value["timeout_seconds"], "request timeout", 1, 120),
        )

    @classmethod
    def load(cls, path: Path, expected_sha256: str) -> HTTPScenario:
        raw = trusted_json(path)
        if hashlib.sha256(canonical_bytes(raw)).hexdigest() != expected_sha256:
            raise ValueError("HTTP definition differs from the admitted scenario inventory")
        return cls.parse(raw)

    def measure(
        self, host: str, port: int, requests: int, check: Callable[[], None], *, unix_socket: Path | None = None
    ) -> list[float]:
        # A numeric address avoids DNS, proxies and selecting production through
        # inherited resolver configuration. The runtime owns endpoint admission.
        ipaddress.ip_address(host)
        positive_integer(port, "private HTTP port", 1, 65535)
        positive_integer(requests, "request count", 1, 10000)
        samples = []
        for number in range(self.warmups + requests):
            check()
            connection = (
                http.client.HTTPConnection(host, port, timeout=self.timeout_seconds)
                if unix_socket is None
                else UnixHTTPConnection(unix_socket, self.timeout_seconds)
            )
            try:
                start = time.perf_counter_ns()
                connection.request(
                    "GET",
                    self.path,
                    headers={"Host": "grow-perf.invalid", "Accept": "application/json", "Connection": "close"},
                )
                response = connection.getresponse()
                lengths = response.headers.get_all("Content-Length", [])
                transfers = response.headers.get_all("Transfer-Encoding", [])
                if (
                    len(lengths) > 1
                    or (lengths and transfers)
                    or (transfers and (len(transfers) != 1 or transfers[0].lower() != "chunked"))
                    or (lengths and (not lengths[0].isascii() or not lengths[0].isdecimal()))
                ):
                    raise ValueError("ambiguous or unsupported HTTP response framing")
                length = int(lengths[0]) if lengths else None
                if length is not None and length > MAX_RESPONSE_BYTES:
                    raise ValueError("scenario response exceeds the size limit")
                content = response.read(MAX_RESPONSE_BYTES + 1)
                elapsed = (time.perf_counter_ns() - start) / 1_000_000
                # read(amt) returns short fixed-length bodies without raising
                # IncompleteRead. A matching JSON prefix must not hide truncation.
                if length is not None and len(content) != length:
                    raise ValueError("incomplete HTTP response body")
                if response.status != self.status or len(content) > MAX_RESPONSE_BYTES:
                    raise ValueError("scenario response status or size differs")
                # Reject redirects, non-JSON, duplicate keys and non-finite values.
                # Correctness work is outside the timed HTTP request interval.
                value = json.loads(content, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
                if hashlib.sha256(canonical_bytes(value)).hexdigest() != self.response_sha256:
                    raise ValueError("scenario response differs from approved correctness digest")
                if elapsed <= 0:
                    raise RuntimeError("HTTP measurement clock did not advance")
                check()
                if number >= self.warmups:
                    samples.append(elapsed)
            finally:
                connection.close()
        return samples


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite response JSON value")
