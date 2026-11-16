from queue import Queue
from threading import RLock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, override_settings
from django.utils import timezone
from django_q.signals import pre_enqueue
from django_q.worker import worker

from grow.workload.admission import AdmissionUnavailable, Lease, admitted, production_activity
from grow.workload.middleware import ProductionAdmissionMiddleware
from grow.workload.workers import prepare_task, register


@pytest.fixture
def coordinator():
    with (
        override_settings(WORKLOAD_COORDINATOR_SOCKET="/run/workload.sock"),
        patch("grow.workload.admission.Lease") as factory,
    ):
        yield factory


def test_activity_is_owned_until_successful_work_finishes(coordinator):
    lease = coordinator.return_value
    with production_activity():
        coordinator.assert_called_once_with("/run/workload.sock", timeout=35, wait=True)
        lease.request.assert_not_called()
        with production_activity():
            assert coordinator.call_count == 1
    lease.request.assert_called_once_with("complete")
    lease.close.assert_called_once_with()


def test_failed_activity_closes_without_acknowledging(coordinator):
    with pytest.raises(ValueError, match="work failed"), production_activity():
        raise ValueError("work failed")
    coordinator.return_value.request.assert_not_called()
    coordinator.return_value.close.assert_called_once_with()


def test_caught_nested_failure_still_keeps_uncertain_receipt(coordinator):
    with production_activity(), pytest.raises(ValueError, match="work failed"), production_activity():
        raise ValueError("nested work failed")
    coordinator.return_value.request.assert_not_called()


def test_disabled_admission_preserves_legacy_execution():
    with override_settings(WORKLOAD_COORDINATOR_SOCKET=""), patch("grow.workload.admission.Lease") as factory:
        with production_activity():
            pass
        factory.assert_not_called()


def test_decorator_covers_direct_calls(coordinator):
    @admitted
    def work(number):
        coordinator.return_value.request.assert_not_called()
        return number + 1

    assert work(2) == 3
    coordinator.return_value.request.assert_called_once_with("complete")


@pytest.mark.parametrize("method", ["get", "head", "options"])
def test_read_requests_do_not_acquire_a_lease(coordinator, method):
    response = HttpResponse()
    middleware = ProductionAdmissionMiddleware(lambda request: response)
    assert middleware(getattr(RequestFactory(), method)("/")) is response
    coordinator.assert_not_called()


@pytest.mark.parametrize("response", [HttpResponse(status=500), StreamingHttpResponse(iter([b"deferred"]))])
def test_uncertain_http_responses_retain_receipts(coordinator, response):
    middleware = ProductionAdmissionMiddleware(lambda request: response)
    assert middleware(RequestFactory().post("/import/")) is response
    coordinator.return_value.request.assert_not_called()
    coordinator.return_value.close.assert_called_once_with()


def test_mutations_are_admitted_before_the_handler(coordinator):
    def handler(request):
        coordinator.assert_called_once()
        coordinator.return_value.request.assert_not_called()
        return HttpResponse(status=202)

    assert ProductionAdmissionMiddleware(handler)(RequestFactory().post("/import/")).status_code == 202
    coordinator.assert_called_once_with("/run/workload.sock", timeout=35, wait=False)
    coordinator.return_value.request.assert_called_once_with("complete")


def test_coordinator_failure_prevents_mutation(coordinator):
    coordinator.side_effect = AdmissionUnavailable("coordinator unavailable")
    handler = MagicMock()
    response = ProductionAdmissionMiddleware(handler)(RequestFactory().post("/import/"))
    assert response.status_code == 503
    assert response["Retry-After"] == "5"
    handler.assert_not_called()


def run_worker(task):
    pending, results = Queue(), Queue()
    task.update(id="worker-task", name="admission-test", started=timezone.now(), sync=False)
    prepare_task("django_q", task)
    pending.put(task)
    pending.put("STOP")
    timer = SimpleNamespace(value=-1, get_lock=RLock)
    with patch("django_q.worker.close_old_django_connections"), patch("django_q.worker.rss_check", return_value=False):
        worker(pending, results, timer)
    return results.get_nowait()


def test_worker_admits_payload_and_publishes_result(coordinator):
    payload = MagicMock(return_value="done")
    result = run_worker({"func": payload, "args": (), "kwargs": {}})
    coordinator.assert_called_once_with("/run/workload.sock", timeout=210, wait=True)
    assert result["success"] is True
    assert result["result"] == "done"
    payload.assert_called_once_with()
    coordinator.return_value.request.assert_called_once_with("complete")


def test_worker_admission_failure_publishes_failure_without_running_payload(coordinator):
    coordinator.side_effect = OSError("coordinator unavailable")
    payload = MagicMock()
    result = run_worker({"func": payload, "args": (19,), "kwargs": {"attempt_id": 7}})
    assert result["func"] is payload
    assert result["args"] == (19,)
    assert result["kwargs"] == {"attempt_id": 7}
    assert result["success"] is False
    assert "coordinator unavailable" in result["result"]
    payload.assert_not_called()


def test_worker_completion_failure_still_publishes_observable_failure(coordinator):
    coordinator.return_value.request.side_effect = OSError("completion unavailable")
    payload = MagicMock(return_value="done")
    result = run_worker({"func": payload, "args": (), "kwargs": {}})
    assert result["success"] is False
    assert "completion unavailable" in result["result"]
    payload.assert_called_once_with()
    coordinator.return_value.close.assert_called_once()


def test_worker_failed_payload_keeps_uncertain_receipt(coordinator):
    payload = MagicMock(side_effect=ValueError("payload failed"))
    result = run_worker({"func": payload, "args": (), "kwargs": {}})
    assert result["success"] is False
    coordinator.return_value.request.assert_not_called()


def test_signal_registration_is_idempotent(coordinator):
    register()
    register()
    task = {"func": "builtins.sum", "args": ([1, 2],), "kwargs": {}}
    pre_enqueue.send(sender="django_q", task=task)
    assert task == {
        "func": "grow.workload.workers.execute",
        "args": ("builtins.sum", ([1, 2],)),
        "kwargs": {},
    }


def test_wire_protocol_and_fragmented_responses():
    with patch("grow.workload.admission.socket.socket") as factory:
        connection = factory.return_value
        connection.recv.side_effect = [b"o", b"k\n", b"ok\n"]
        lease = Lease("/run/workload.sock")
        connection.settimeout.assert_called_once_with(35)
        connection.connect.assert_called_once_with("/run/workload.sock")
        lease.request("complete")
        assert [args.args[0] for args in connection.sendall.call_args_list] == [b"production\n", b"complete\n"]
        lease.close()
        connection.close.assert_called_once()


def test_nowait_wire_request_and_refusal_close_without_completion():
    with patch("grow.workload.admission.socket.socket") as factory:
        connection = factory.return_value
        connection.recv.return_value = b"refused\n"
        with pytest.raises(AdmissionUnavailable):
            Lease("/run/workload.sock", wait=False)
        connection.sendall.assert_called_once_with(b"production-nowait\n")
        connection.close.assert_called_once()


@pytest.mark.parametrize("response", [b"refused\n", b"", b"x" * 256])
def test_wire_failure_closes_without_leaking_socket(response):
    with patch("grow.workload.admission.socket.socket") as factory:
        connection = factory.return_value
        connection.recv.return_value = response
        with pytest.raises(RuntimeError):
            Lease("/run/workload.sock")
        connection.close.assert_called_once()


def test_wrapped_string_task_preserves_function_and_arguments(coordinator):
    result = run_worker({"func": "builtins.sorted", "args": ([1, 3, 2],), "kwargs": {"reverse": True}})
    assert result["success"] is True
    assert result["result"] == [3, 2, 1]
    assert result["func"] == "builtins.sorted"
    assert result["args"] == ([1, 3, 2],)
    assert result["kwargs"] == {"reverse": True}


def test_task_keyword_names_do_not_collide_with_wrapper(coordinator):
    payload = MagicMock(return_value="done")
    result = run_worker({"func": payload, "args": (), "kwargs": {"function": "value", "args": 7}})
    assert result["success"] is True
    payload.assert_called_once_with(function="value", args=7)


def test_disabled_admission_preserves_serialized_task_contract():
    task = {"func": "builtins.sum", "args": ([1, 2],), "kwargs": {}}
    with override_settings(WORKLOAD_COORDINATOR_SOCKET=""):
        prepare_task("django_q", task)
    assert task == {"func": "builtins.sum", "args": ([1, 2],), "kwargs": {}}
