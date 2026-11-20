"""Approved Django settings for the benchmark: the real settings with inert secrets and no outbound services.

Shared by the base and the head code, so a setting one version does not know must stay harmless. DATABASE_URL and
DJANGO_SETTINGS_MODULE come from the runtime; the values below only satisfy the required-variable lookups.
"""

import os

for _name, _value in {
    "SECRET_KEY": "grow-perf-inert-secret-key",
    "PIPELINE_API_KEY": "grow-perf-inert",
    "CURATION_API_KEY": "grow-perf-inert",
    "GOOGLE_OAUTH_CLIENT_ID": "grow-perf-inert",
    "ADMIN_GOOGLE_SUB": "grow-perf-inert",
    "YOUTUBE_API_KEY": "grow-perf-inert",
    "REDIS_URL": "redis://127.0.0.1:6379/0",
}.items():
    os.environ[_name] = _value
os.environ["DEBUG"] = "false"

from grow.settings import *  # noqa: F403

DEBUG = False
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
