import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

START_TIME = time.time()


class HealthCheckView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        health_status = {
            "status": "healthy",
            "version": getattr(settings, "APP_VERSION", "unknown"),
            "uptime_seconds": int(time.time() - START_TIME),
            "checks": {},
        }

        db_healthy = self._check_database(health_status)
        self._check_cache(health_status)

        if not db_healthy:
            health_status["status"] = "unhealthy"
            return Response(health_status, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(health_status, status=status.HTTP_200_OK)

    def _check_database(self, health_status):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")

            health_status["checks"]["database"] = {"status": "ok", "vendor": connection.vendor}
            return True

        except Exception as e:
            health_status["checks"]["database"] = {"status": "error", "message": str(e)}
            return False

    def _check_cache(self, health_status):
        try:
            test_key = "health_check_test"
            cache.set(test_key, "ok", timeout=10)
            result = cache.get(test_key)

            health_status["checks"]["cache"] = {"status": "ok" if result == "ok" else "warning"}

        except Exception as e:
            health_status["checks"]["cache"] = {"status": "warning", "message": str(e)}
