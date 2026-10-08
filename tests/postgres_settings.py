import os

import dj_database_url

from tests.settings import *  # noqa: F403

# The bulk song import loads parts with COPY, which SQLite lacks.
DATABASES = {"default": dj_database_url.parse(os.environ["POSTGRES_TEST_DATABASE_URL"])}
