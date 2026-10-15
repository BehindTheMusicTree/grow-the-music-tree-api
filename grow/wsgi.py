import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "grow.settings")

# Web workers only: migrate (index builds) and the import cluster legitimately run statements for minutes.
if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    timeout_ms = int(os.environ["WEB_DB_STATEMENT_TIMEOUT_MS"])
    options = settings.DATABASES["default"]["OPTIONS"]
    options["options"] += f" -c statement_timeout={timeout_ms}"

application = get_wsgi_application()
