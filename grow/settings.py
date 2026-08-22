import os
from pathlib import Path

import dj_database_url
from the_music_tree_genre_kit.data import DATA_DIR

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["SECRET_KEY"]

SYSTEM_USERNAME = os.environ["SYSTEM_USERNAME"]

GROW_API_KEY = os.environ["GROW_API_KEY"]

DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]

CORS_ALLOWED_ORIGINS = [o for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "corsheaders",
    "the_music_tree_genre_kit",
    "grow",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "grow.urls"

WSGI_APPLICATION = "grow.wsgi.application"

DATABASES = {
    "default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=600),
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "the_music_tree_api_kit.view.error.exception_handler.custom_exception_handler",
}

APP_VERSION = os.environ["APP_VERSION"]

API_ROOT_BASE = f"v{APP_VERSION.split('.')[0]}/"

CRITERIA_MODEL = "grow.Criteria"
TRACK_MODEL = "grow.YoutubeTrack"
ARTIST_MODEL = "grow.Artist"
ALBUM_MODEL = "grow.Album"

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
