import logging
import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Any

from django.conf import settings
from django.db import connection
from django.utils import timezone
from psycopg import connect
from psycopg.types.json import Jsonb

from grow.bulk_import.ImportAttempt import ImportAttempt

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30
TERMINAL_STATES = ("succeeded", "failed", "interrupted")
_current: ContextVar[ProgressReporter | None] = ContextVar("import_progress", default=None)


class ProgressReporter:
    """One connection, owned by one thread; no telemetry write joins the business transaction."""

    def __init__(self, attempt: ImportAttempt):
        self.attempt = attempt
        self.events: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=128)
        self.ready = threading.Event()
        self.error: Exception | None = None
        self.thread: threading.Thread | None = None
        self.threaded = settings.IMPORT_PROGRESS_THREADED and connection.vendor == "postgresql"
        self.db_params = connection.get_connection_params() if self.threaded else {}
        if self.threaded:
            self.db_params["connect_timeout"] = 5
        self.db = None
        self.commit_started: float | None = None

    def start(self):
        if not self.threaded:
            return
        self.thread = threading.Thread(target=self._run, name=f"import-progress-{self.attempt.pk}", daemon=True)
        self.thread.start()
        self.ready.wait()
        if self.error is not None:
            self.thread.join()
            raise RuntimeError("could not initialize import progress connection") from self.error

    def _write(self, values):
        if self.db is None:
            ImportAttempt.objects.filter(pk=self.attempt.pk).exclude(state__in=TERMINAL_STATES).update(**values)
            return
        assignments, params = [], []
        for key, value in values.items():
            assignments.append(f'"{key}" = %s')
            params.append(Jsonb(value) if key in {"completed_steps", "result"} else value)
        with self.db.cursor() as cursor:
            cursor.execute(
                f"UPDATE grow_import_attempt SET {', '.join(assignments)}"
                " WHERE id = %s AND state NOT IN ('succeeded', 'failed', 'interrupted')",
                [*params, self.attempt.pk],
            )

    def _run(self):
        db = None
        try:
            db = connect(**self.db_params, autocommit=True)
            self.db = db
            with db.cursor() as cursor:
                cursor.execute("SET statement_timeout = '5s'")
                cursor.execute("SET lock_timeout = '2s'")
                cursor.execute("SELECT 1 FROM grow_import_attempt WHERE id = %s", [self.attempt.pk])
                if cursor.fetchone() is None:
                    raise RuntimeError("import attempt must be committed before reporter startup")
            self.ready.set()
            while True:
                try:
                    event = self.events.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    event = {}
                if event is None:
                    break
                self._write({**event, "heartbeat_at": timezone.now()})
        except Exception as exc:
            self.error = exc
            logger.exception(
                "import run %s attempt %s progress reporter unavailable", self.attempt.run_id, self.attempt.attempt
            )
        finally:
            self.ready.set()
            if db is not None:
                db.close()

    def publish(self, **values):
        if self.error is not None:
            return
        if not self.threaded:
            self._write({**values, "heartbeat_at": timezone.now()})
            return
        try:
            self.events.put_nowait(values)
        except queue.Full:
            # Losing telemetry must not roll back healthy business writes. The last heartbeat becomes stale.
            self.error = RuntimeError("import progress queue full")
            logger.error("import run %s progress queue full", self.attempt.run_id)

    def close(self):
        if self.thread is not None and self.thread.is_alive():
            while self.thread.is_alive():
                try:
                    self.events.put(None, timeout=1)
                    break
                except queue.Full:
                    continue
            self.thread.join()

    @contextmanager
    def step(self, label: str) -> Iterator[dict[str, Any]]:
        now = timezone.now()
        self.publish(step=label, step_started_at=now, last_progress_at=now)
        logger.info("import run=%s kind=%s mode=%s attempt=%s step=%s started", *self.identity, label)
        started = perf_counter()
        timing: dict[str, Any] = {"label": label, "rowcount": None}
        yield timing
        timing["ms"] = int((perf_counter() - started) * 1000)
        self.attempt.completed_steps = [*self.attempt.completed_steps, timing]
        self.publish(completed_steps=self.attempt.completed_steps, last_progress_at=timezone.now())
        logger.info(
            "import run=%s kind=%s mode=%s attempt=%s step=%s rowcount=%s ms=%s",
            *self.identity,
            label,
            timing["rowcount"],
            timing["ms"],
        )

    @property
    def identity(self):
        return self.attempt.run_id, self.attempt.kind, self.attempt.mode, self.attempt.attempt


@contextmanager
def report_step(label: str) -> Iterator[dict[str, Any]]:
    reporter = _current.get()
    if reporter is None:
        yield {}
    else:
        with reporter.step(label) as timing:
            yield timing


def committing():
    reporter = _current.get()
    if reporter is not None:
        reporter.commit_started = perf_counter()
        logger.info("import run=%s kind=%s mode=%s attempt=%s step=commit started", *reporter.identity)
        reporter.publish(
            state=ImportAttempt.State.COMMITTING,
            step="commit",
            step_started_at=timezone.now(),
            last_progress_at=timezone.now(),
        )


def committed():
    reporter = _current.get()
    if reporter is not None and reporter.commit_started is not None:
        timing = {"label": "commit", "rowcount": None, "ms": int((perf_counter() - reporter.commit_started) * 1000)}
        reporter.attempt.completed_steps = [*reporter.attempt.completed_steps, timing]
        reporter.publish(completed_steps=reporter.attempt.completed_steps, last_progress_at=timezone.now())
        logger.info("import run=%s kind=%s mode=%s attempt=%s step=commit ms=%s", *reporter.identity, timing["ms"])


def activate(reporter: ProgressReporter):
    return _current.set(reporter)


def deactivate(token):
    _current.reset(token)
