"""Production admission covers the executing work, independently of its submitter."""

import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any

from django.conf import settings


@dataclass
class Activity:
    complete: bool = True


_active: ContextVar[Activity | None] = ContextVar("grow_workload_active", default=None)


class Lease:
    def __init__(self, endpoint: str):
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.settimeout(35)
        self.buffer = b""
        try:
            self.connection.connect(endpoint)
            self.request("production")
        except BaseException:
            self.close()
            raise

    def request(self, operation: str) -> None:
        self.connection.sendall((operation + "\n").encode("ascii"))
        while b"\n" not in self.buffer:
            block = self.connection.recv(256)
            if not block or len(self.buffer) + len(block) > 512:
                raise RuntimeError("Invalid workload coordinator response")
            self.buffer += block
        response, self.buffer = self.buffer.split(b"\n", 1)
        if response != b"ok":
            raise RuntimeError("Production workload admission refused")

    def close(self) -> None:
        self.connection.close()


@contextmanager
def production_activity() -> Iterator[Activity]:
    endpoint = settings.WORKLOAD_COORDINATOR_SOCKET
    active = _active.get()
    if active is not None:
        try:
            yield active
        except BaseException:
            active.complete = False
            raise
        return
    activity = Activity()
    if not endpoint:
        yield activity
        return
    lease = Lease(endpoint)
    token = _active.set(activity)
    try:
        yield activity
        if activity.complete:
            lease.request("complete")
    finally:
        _active.reset(token)
        lease.close()


def admitted(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with production_activity():
            return function(*args, **kwargs)

    return wrapped
