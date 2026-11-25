import uuid

from drf_spectacular.utils import OpenApiParameter
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.request import Request

from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest

HEADER = "X-Pipeline-Run-Request"
HEADER_PARAMETER = OpenApiParameter(
    HEADER,
    str,
    location=OpenApiParameter.HEADER,
    required=False,
    description="UUID of the running pipeline run this import belongs to, so its progress shows on that run.",
)


class PipelineRunNotRunning(APIException):
    status_code = 409
    default_detail = "The pipeline run is not running"


def linked_pipeline_run(request: Request) -> PipelineRunRequest | None:
    """
    The pipeline run an import is made for, named by the `X-Pipeline-Run-Request` header; None when it is absent.
    A malformed or unknown uuid is a 400, and a run that is not `running` a 409: `expire_stale` ends a run whose
    poller stopped beating, so a late import must not attach to it.
    """
    raw = request.headers.get(HEADER)
    if raw is None:
        return None
    try:
        run_uuid = uuid.UUID(raw)
    except ValueError:
        raise ValidationError({"message": f"Unknown pipeline run {raw}"}) from None
    run = PipelineRunRequest.objects.filter(uuid=run_uuid).first()
    if run is None:
        raise ValidationError({"message": f"Unknown pipeline run {raw}"})
    if run.status != PipelineRunRequest.Status.RUNNING:
        raise PipelineRunNotRunning(f"Pipeline run {raw} is {run.status}, not running")
    return run
