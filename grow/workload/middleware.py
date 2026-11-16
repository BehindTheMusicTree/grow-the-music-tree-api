"""Gate mutations before upload, database work or asynchronous submission."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from grow.workload.admission import production_activity


class ProductionAdmissionMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return self.get_response(request)
        with production_activity() as activity:
            response = self.get_response(request)
            if response.status_code >= 500 or response.streaming:
                # An error or deferred response cannot prove the work completed.
                activity.complete = False
            return response
