import os

import dj_database_url

from tests.settings import *  # noqa: F403

# Postgres, not SQLite: in-memory SQLite hides the per-query round trip that N+1s cost in production.
DATABASES = {"default": dj_database_url.parse(os.environ["PERF_DATABASE_URL"])}

# Prod's camelCase wire format: the Gold exports are camelCase, and rendering cost is part of the latency.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": ("djangorestframework_camel_case.render.CamelCaseJSONRenderer",),
    "DEFAULT_PARSER_CLASSES": ("djangorestframework_camel_case.parser.CamelCaseJSONParser",),
}
