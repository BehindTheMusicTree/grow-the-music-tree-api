from django.db.utils import OperationalError
from psycopg.errors import QueryCanceled
from rest_framework.exceptions import APIException
from the_music_tree_api_kit.view.error.exception_handler import custom_exception_handler


class QueryTimeout(APIException):
    status_code = 503
    default_detail = "The request took too long to process. Try again."
    default_code = "query_timeout"


def exception_handler(exc, context):
    """A statement_timeout cancel frees the worker; report it as retryable instead of a 500."""
    if isinstance(exc, OperationalError) and isinstance(exc.__cause__, QueryCanceled):
        exc = QueryTimeout()
    return custom_exception_handler(exc, context)
