"""Exercise inode-pinned Unix connections against real Linux sockets."""

import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.catalogue.scenario_execution import UnixHTTPConnection


@unittest.skipUnless(hasattr(os, "O_PATH"), "requires Linux pinned Unix sockets")
class UnixHTTPTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gp-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "api.sock"

    def listener(self, path):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(str(path))
        listener.listen(1)
        listener.settimeout(0.1)
        return listener

    def connection(self):
        connection = UnixHTTPConnection(self.path, 1)
        self.addCleanup(connection.close)
        return connection

    def test_legitimate_socket_connects(self):
        listener = self.listener(self.path)
        self.connection().connect()
        accepted, _ = listener.accept()
        accepted.close()

    def test_symlinks_regular_files_and_fifos_are_refused(self):
        target = self.root / "host.sock"
        listener = self.listener(target)
        for link in (target, Path(target.name)):
            with self.subTest(link=link):
                self.path.symlink_to(link)
                with self.assertRaises(ValueError):
                    self.connection().connect()
                self.path.unlink()
        self.path.write_text("not a socket")
        with self.assertRaises(ValueError):
            self.connection().connect()
        self.path.unlink()
        os.mkfifo(self.path)
        with self.assertRaises(ValueError):
            self.connection().connect()
        with self.assertRaises(TimeoutError):
            listener.accept()

    def test_replacement_after_open_cannot_redirect_to_host_socket(self):
        original = self.listener(self.path)
        target = self.root / "host.sock"
        hostile = self.listener(target)
        real_open = os.open
        descriptors = []

        def replace_after_open(path, flags):
            descriptor = real_open(path, flags)
            descriptors.append(descriptor)
            self.path.rename(self.root / "original.sock")
            self.path.symlink_to(target)
            return descriptor

        with patch("benchmarks.catalogue.scenario_execution.os.open", side_effect=replace_after_open):
            self.connection().connect()
        accepted, _ = original.accept()
        accepted.close()
        with self.assertRaises(TimeoutError):
            hostile.accept()
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_failed_connect_closes_socket_and_pinned_descriptor(self):
        listener = self.listener(self.path)
        listener.close()
        connection = self.connection()
        real_open = os.open
        descriptors = []

        def record_open(path, flags):
            descriptor = real_open(path, flags)
            descriptors.append(descriptor)
            return descriptor

        with (
            patch("benchmarks.catalogue.scenario_execution.os.open", side_effect=record_open),
            self.assertRaises(ConnectionRefusedError),
        ):
            connection.connect()
        self.assertIsNone(connection.sock)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])


if __name__ == "__main__":
    unittest.main()
