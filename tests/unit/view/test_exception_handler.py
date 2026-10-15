from django.db.utils import OperationalError
from psycopg.errors import QueryCanceled

from grow.view.error.exception_handler import exception_handler


def test_statement_timeout_maps_to_503():
    error = OperationalError("canceling statement due to statement timeout")
    error.__cause__ = QueryCanceled()

    response = exception_handler(error, {})

    assert response.status_code == 503
