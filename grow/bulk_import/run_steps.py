import logging
from collections.abc import Iterable
from time import perf_counter
from typing import Any

from django.db.backends.utils import CursorWrapper

logger = logging.getLogger(__name__)


def run_steps(cursor: CursorWrapper, steps: Iterable[tuple[str, str]], params: dict[str, Any]) -> None:
    """Executes `(label, sql)` merge steps in order, logging each one's rowcount and duration."""
    for label, sql in steps:
        started = perf_counter()
        cursor.execute(sql, params)
        logger.info(
            "bulk import step %s rowcount=%d in %d ms", label, cursor.rowcount, (perf_counter() - started) * 1000
        )
