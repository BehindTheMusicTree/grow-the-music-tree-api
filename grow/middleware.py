DEPRECATED_PREFIX = "/v0/"
# RFC 9745 Deprecation (structured-field date: 2026-09-24) and RFC 8594 Sunset (HTTP-date).
DEPRECATION = "@1790208000"
SUNSET = "Thu, 24 Dec 2026 00:00:00 GMT"


class DeprecationHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(DEPRECATED_PREFIX):
            response["Deprecation"] = DEPRECATION
            response["Sunset"] = SUNSET
        return response
