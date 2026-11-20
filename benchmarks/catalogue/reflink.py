"""Copy-on-write clones of a restored data directory, so each round starts from the same bytes.

A catalogue restore plus preparation takes hours; every benchmark round then needs a pristine database. A reflink
clone is O(metadata) and shares blocks with the source until written, so the restore runs once per side. There is no
fallback to a plain copy: a multi-hundred-GB byte copy per round would silently distort the harness, so an
unsupported filesystem is an error.
"""

import shutil
import subprocess
import uuid
from pathlib import Path

COPY = "cp"


def _clone(source: Path, destination: Path) -> None:
    try:
        subprocess.run(
            [COPY, "-a", "--reflink=always", "--", str(source), str(destination)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60 * 60,
        )
    except FileNotFoundError as error:
        raise RuntimeError("reflink clones need GNU cp on PATH") from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "reflink clone failed; the workspace needs a filesystem with reflink support (XFS with reflink=1, "
            "btrfs): " + (error.stderr or "").strip()[-300:]
        ) from error


def require_reflink(directory: Path) -> None:
    """Fail before an hours-long restore when `directory` cannot hold reflink clones."""
    probe = directory / ("reflink-probe-" + uuid.uuid4().hex[:8])
    source, target = probe.with_suffix(".src"), probe.with_suffix(".dst")
    try:
        source.write_bytes(b"reflink probe\n" * 1024)
        _clone(source, target)
    finally:
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)


def clone_directory(source: Path, parent: Path, name: str) -> Path:
    """Reflink-clone the stopped database directory `source` into a new private directory under `parent`."""
    if (source / "postmaster.pid").exists():
        raise RuntimeError("refusing to clone a data directory whose server is still running")
    destination = parent / (name + "-" + uuid.uuid4().hex[:8])
    try:
        _clone(source, destination)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination
