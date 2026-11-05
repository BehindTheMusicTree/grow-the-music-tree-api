import logging
from collections.abc import Iterable
from time import perf_counter
from typing import Any

from django.db.backends.utils import CursorWrapper

from grow.bulk_import.progress import report_step

logger = logging.getLogger(__name__)


def run_steps(cursor: CursorWrapper, steps: Iterable[tuple[str, str]], params: dict[str, Any]) -> list[dict[str, Any]]:
    """Executes `(label, sql)` merge steps in order, logging each one's rowcount and duration and returning them."""
    timings = []
    for label, sql in steps:
        started = perf_counter()
        logger.info("bulk import run %s step %s started", params["run"], label)
        with report_step(label) as timing:
            cursor.execute(sql, params)
            timing["rowcount"] = cursor.rowcount
            timing["type"] = "sql"
        ms = int((perf_counter() - started) * 1000)
        logger.info("bulk import run %s step %s rowcount=%d in %d ms", params["run"], label, cursor.rowcount, ms)
        timings.append({"label": label, "rowcount": cursor.rowcount, "ms": ms})
    return timings
