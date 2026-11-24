REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ("djangorestframework_camel_case.render.CamelCaseJSONRenderer",),
    "DEFAULT_PARSER_CLASSES": (
        "djangorestframework_camel_case.parser.CamelCaseJSONParser",
        "djangorestframework_camel_case.parser.CamelCaseMultiPartParser",
        "djangorestframework_camel_case.parser.CamelCaseFormParser",
    ),
    "DEFAULT_PERMISSION_CLASSES": ["grow.view.permission.IsAdminOrReadOnly.IsAdminOrReadOnly"],
    "DEFAULT_THROTTLE_RATES": {"artist-search": "120/min", "song-search": "120/min", "genre-search": "120/min"},
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "grow.view.error.exception_handler.exception_handler",
}

# `row` holds a curation list's CSV columns, which stay snake_case on the wire.
JSON_CAMEL_CASE = {"JSON_UNDERSCOREIZE": {"ignore_fields": ("row",)}}

SPECTACULAR_SETTINGS = {
    "TITLE": "TheMusicTree grow API",
    # Static on purpose: a release bump must not stale the committed openapi.yaml.
    "VERSION": "1",
    "PREPROCESSING_HOOKS": ["grow.openapi.hooks.drop_unimplemented_actions"],
    "ENUM_NAME_OVERRIDES": {
        "HistoryAction": "grow.model.history.HistoryAction.HistoryAction",
        "ImportRunModeEnum": "grow.bulk_import.BulkImportRun.BulkImportRun.Mode",
    },
    "SERVE_INCLUDE_SCHEMA": False,
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.contrib.djangorestframework_camel_case.camelize_serializer_fields",
        "drf_spectacular.hooks.postprocess_schema_enums",
    ],
    "CAMELIZE_NAMES": False,
}
