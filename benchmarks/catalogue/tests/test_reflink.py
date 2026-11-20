"""Reflink clone helper: fails fast without reflink support, never falls back to a byte copy."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmarks.catalogue import reflink


class ReflinkTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="grow-reflink-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def failing(self, stderr="failed to clone: Operation not supported"):
        return subprocess.CalledProcessError(1, "cp", stderr=stderr)

    def test_unsupported_filesystem_is_an_error_not_a_fallback(self):
        with (
            mock.patch.object(reflink.subprocess, "run", side_effect=self.failing()) as run,
            self.assertRaisesRegex(RuntimeError, "reflink support"),
        ):
            reflink.require_reflink(self.root)
        self.assertIn("--reflink=always", run.call_args.args[0])
        self.assertEqual([], list(self.root.iterdir()))

    def test_non_gnu_cp_is_reported_as_such(self):
        error = self.failing("cp: illegal option -- -")
        with (
            mock.patch.object(reflink.subprocess, "run", side_effect=error),
            self.assertRaisesRegex(RuntimeError, "GNU cp"),
        ):
            reflink.require_reflink(self.root)

    def test_missing_cp_is_reported(self):
        with (
            mock.patch.object(reflink.subprocess, "run", side_effect=FileNotFoundError),
            self.assertRaisesRegex(RuntimeError, "GNU cp"),
        ):
            reflink.require_reflink(self.root)

    def test_running_server_is_never_cloned(self):
        source = self.root / "data"
        source.mkdir()
        (source / "postmaster.pid").write_text("1\n")
        with (
            mock.patch.object(reflink.subprocess, "run") as run,
            self.assertRaisesRegex(RuntimeError, "still running"),
        ):
            reflink.clone_directory(source, self.root, "round")
        run.assert_not_called()

    def test_failed_clone_leaves_no_partial_directory(self):
        source = self.root / "data"
        source.mkdir()

        def partial(arguments, **_):
            Path(arguments[-1]).mkdir()
            raise self.failing()

        with (
            mock.patch.object(reflink.subprocess, "run", side_effect=partial),
            self.assertRaises(RuntimeError),
        ):
            reflink.clone_directory(source, self.root, "round")
        self.assertEqual(["data"], [path.name for path in self.root.iterdir()])

    def test_clone_is_independent_on_a_reflink_filesystem(self):
        # CI points GROW_PERF_REFLINK_DIR at a btrfs mount, where support is required and a failure is a failure.
        configured = os.environ.get("GROW_PERF_REFLINK_DIR")
        root = Path(configured) if configured is not None else self.root
        if configured is None:
            try:
                reflink.require_reflink(root)
            except RuntimeError as error:
                self.skipTest(f"workspace filesystem lacks reflink support: {error}")
        reflink.require_reflink(root)
        source = root / ("data-" + self.id())
        source.mkdir()
        self.addCleanup(shutil.rmtree, source, ignore_errors=True)
        (source / "PG_VERSION").write_text("16\n")
        clone = reflink.clone_directory(source, root, "round")
        self.addCleanup(shutil.rmtree, clone, ignore_errors=True)
        (clone / "PG_VERSION").write_text("changed\n")
        self.assertEqual("16\n", (source / "PG_VERSION").read_text())


if __name__ == "__main__":
    unittest.main()
