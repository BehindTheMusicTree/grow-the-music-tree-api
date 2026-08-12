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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SYSTEM_USERNAME = "system"

CRITERIA_TYPE_LABEL_LEN_MAX = 50
CRITERIA_NAME_LEN_MAX = 256
CRITERIA_TREE_IMPORT_MAX_ROOT_COUNT = 1000
CRITERIA_TREE_IMPORT_MAX_TOTAL_COUNT = 30000

ARTIST_NAME_LEN_MAX = 256
ALBUM_NAME_LEN_MAX = 256
MANUAL_PLAYLIST_NAME_LEN_MAX = 256
UPLOADED_TRACK_TITLE_LEN_MAX = 256
UPLOADED_TRACK_TRACK_NUMBER_MAX = 1000
UPLOADED_TRACK_RATING_VALUE_MAX = 10
LANGUAGE_LEN_MAX = 3
