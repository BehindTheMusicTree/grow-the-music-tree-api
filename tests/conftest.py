import unicodedata

from django.db.backends.signals import connection_created


def _grow_search_norm(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).lower()


def _register_search_norm(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        connection.connection.create_function("grow_search_norm", 1, _grow_search_norm, deterministic=True)


connection_created.connect(_register_search_norm)
