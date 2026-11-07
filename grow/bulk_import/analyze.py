from collections.abc import Iterable

from django.db import connection
from django.db.models import Model


def tables(models: Iterable[type[Model]]) -> list[str]:
    """The distinct tables behind `models`, in order (multi-table inheritance children share a parent's table)."""
    return list(dict.fromkeys(model._meta.db_table for model in models))


def analyze_steps(models: Iterable[type[Model]]) -> list[tuple[str, str]]:
    """
    Merge steps refreshing the planner statistics of the tables a bulk merge rewrote. Run inside the merge's
    transaction, so the statistics commit with the data. Otherwise, until autoanalyze catches up, queries plan
    against the pre-merge row counts and can run several times slower (a perf scenario went from 178 ms to 1170 ms).
    """
    return [(f"analyze_{table}", f"ANALYZE {table}") for table in tables(models)]


def analyze(models: Iterable[type[Model]]) -> None:
    """Runs `analyze_steps` outside a step-recorded merge, on the default connection's current transaction."""
    with connection.cursor() as cursor:
        for _, sql in analyze_steps(models):
            cursor.execute(sql)
