"""Queue admission runs inside django-q's payload exception boundary."""

import pydoc
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django_q.signals import post_execute_in_worker, pre_enqueue

from grow.workload.admission import production_activity

_EXECUTOR = "grow.workload.workers.execute"


def execute(function: str | Callable[..., Any], args: tuple[Any, ...], /, **kwargs: Any) -> Any:
    with production_activity(timeout=210):
        target = pydoc.locate(function) if isinstance(function, str) else function
        if not callable(target):
            raise ValueError(f"Function {function!r} is not defined")
        return target(*args, **kwargs)


def prepare_task(sender: Any, task: dict[str, Any], **kwargs: Any) -> None:
    if not settings.WORKLOAD_COORDINATOR_SOCKET or task["func"] == _EXECUTOR:
        return
    task["args"] = (task["func"], task["args"])
    task["func"] = _EXECUTOR


def restore_task(sender: Any, task: dict[str, Any], **kwargs: Any) -> None:
    # Result consumers identify imports by their original function and attempt_id.
    if task.get("func") == _EXECUTOR:
        task["func"], task["args"] = task["args"]


def register() -> None:
    pre_enqueue.connect(prepare_task, weak=False, dispatch_uid="grow_workload_admission_enqueue")
    post_execute_in_worker.connect(restore_task, weak=False, dispatch_uid="grow_workload_admission_result")
