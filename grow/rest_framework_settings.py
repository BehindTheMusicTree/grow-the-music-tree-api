REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ("djangorestframework_camel_case.render.CamelCaseJSONRenderer",),
    "DEFAULT_PARSER_CLASSES": (
        "djangorestframework_camel_case.parser.CamelCaseJSONParser",
        "djangorestframework_camel_case.parser.CamelCaseMultiPartParser",
        "djangorestframework_camel_case.parser.CamelCaseFormParser",
    ),
    "DEFAULT_PERMISSION_CLASSES": ["grow.view.permission.IsAdminOrReadOnly.IsAdminOrReadOnly"],
    "EXCEPTION_HANDLER": "grow.view.error.exception_handler.exception_handler",
}

# `row` holds a curation list's CSV columns, which stay snake_case on the wire.
JSON_CAMEL_CASE = {"JSON_UNDERSCOREIZE": {"ignore_fields": ("row",)}}
