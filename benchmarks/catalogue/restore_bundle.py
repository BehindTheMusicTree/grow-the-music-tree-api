"""Load independently approved restore inputs before touching a scratch database.

The operator installs this bundle outside candidate access. This module never
creates approvals from supplied SQL or treats projection as benchmark success.
"""

import os
import stat
from pathlib import Path

from .manifest import Session, trusted_json
from .private_files import private_path
from .restore_execution import Approval, Postgres, restore

MAX_SCHEMA_BYTES = 64 * 1024**2


def schema_bytes(path: Path) -> bytes:
    private_path(path, directory=False)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or not 0 < info.st_size <= MAX_SCHEMA_BYTES
        ):
            raise ValueError("schema must be a private root-owned regular file of at most 64 MiB")
        content = source.read(MAX_SCHEMA_BYTES + 1)
    if not 0 < len(content) <= MAX_SCHEMA_BYTES:
        raise ValueError("schema size exceeds restore limit")
    content.decode("utf-8")
    return content


def restore_approved(database: Postgres, session: Session, directory: Path) -> dict:
    """Validate all operator inputs before the first transport operation.

    The caller must still hold admission, exclusive storage and supervision,
    and discard failed databases. Each side/round requires a new database.
    """
    private_path(directory, directory=True)
    approval = Approval.parse(trusted_json(directory / "approval.json"))
    if approval.backup_sha256 != session.backup_sha256:
        raise ValueError("restore approval differs from session backup")
    pre_data = schema_bytes(directory / "pre-data.sql")
    post_data = schema_bytes(directory / "post-data.sql")
    approval.verify(pre_data, post_data)
    return restore(database, approval, pre_data, post_data)
