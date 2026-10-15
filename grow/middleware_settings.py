MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "the_music_tree_api_kit.view.middleware.HostValidationMiddleware.HostValidationMiddleware",
    "django.middleware.http.ConditionalGetMiddleware",
    "django.middleware.common.CommonMiddleware",
    "the_music_tree_api_kit.view.middleware.CamelToSnakeMiddleware.CamelToSnakeMiddleware",
]
