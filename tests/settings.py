import os

from the_music_tree_genre_kit.data import DATA_DIR

SECRET_KEY = "fixture-only-not-for-production"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "the_music_tree_genre_kit",
    "grow",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "grow.urls"

API_ROOT_BASE = "v0/"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "the_music_tree_api_kit.view.error.exception_handler.custom_exception_handler",
}

SYSTEM_USERNAME = os.environ.setdefault("SYSTEM_USERNAME", "system")

GROW_API_KEY = "test-api-key"

PAGINATION_PAGE_SIZE_DEFAULT = 30
PAGINATION_PAGE_SIZE_MAX = 100

CRITERIA_TYPE_LABEL_LEN_MAX = 255
CRITERIA_NAME_LEN_MAX = 256
CRITERIA_TREE_IMPORT_MAX_ROOT_COUNT = 1000
CRITERIA_TREE_IMPORT_MAX_TOTAL_COUNT = 30000

ARTIST_NAME_LEN_MAX = 256
ALBUM_NAME_LEN_MAX = 256
MANUAL_PLAYLIST_NAME_LEN_MAX = 256
TRACK_TITLE_LEN_MAX = 256
TRACK_TRACK_NUMBER_MAX = 1000
TRACK_RATING_VALUE_MAX = 10
LANGUAGE_LEN_MAX = 3
YOUTUBE_TRACK_VIDEO_ID_LEN_MAX = 11
