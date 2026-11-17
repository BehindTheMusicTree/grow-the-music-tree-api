"""Root-private file helpers shared by the benchmark runtimes.

Kept free of host-specific coordination or storage reservation so that both the
archived VPS controller and the hosted runtime can depend on it.
"""

import os
import stat
from pathlib import Path


def private_path(path: Path, *, directory: bool) -> None:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("canonical storage path required")
    for ancestor in path.parents:
        info = ancestor.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("storage ancestors must be exclusively root writable")
    info = path.stat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("private root-owned storage path required")
    if not directory and info.st_nlink != 1:
        raise ValueError("backing file must not have aliases")


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
