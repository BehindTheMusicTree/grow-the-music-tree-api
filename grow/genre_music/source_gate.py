from django.db import connections


def lock_catalogue_sources(*, using: str = "default") -> None:
    """Take the existing source gate before loading state for a managed mutation."""
    if connections[using].vendor == "postgresql":
        with connections[using].cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone()[0] != "read committed":
                raise ValueError("Catalogue writes require READ COMMITTED isolation")
            cursor.execute("SELECT pg_advisory_xact_lock(716731928417)")
