import os

import dj_database_url

from tests.settings import *  # noqa: F403

# Postgres, not SQLite: in-memory SQLite hides the per-query round trip that N+1s cost in production.
DATABASES = {"default": dj_database_url.parse(os.environ["PERF_DATABASE_URL"])}
